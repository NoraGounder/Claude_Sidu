"""Polite, cheap website crawler for Layer 2.

- Plain HTTP first (requests + BeautifulSoup). Most company sites render on the server.
- Crawl4AI is used only when installed and a page comes back almost empty (JavaScript sites).
- Respects robots.txt, identifies itself, caps page size, and caches every page in
  data/crawl_cache/ so re-scoring never re-crawls.
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from gtm import jobboards
from gtm.config import data_dir

USER_AGENT = "QuailworksBot/0.1 (+https://quailworks.co; company research)"
MAX_BYTES = 1_500_000
TIMEOUT = 12

CAREERS_HINTS = re.compile(
    r"(vacature|vacatures|werken-bij|werkenbij|werken bij|kom werken|carriere|carrière|careers?"
    r"|jobs?|vacanc|banen|join us|solliciteer)", re.I)
JOB_LINK_HINTS = re.compile(r"(vacature|vacancy|vacancies|/job|/jobs/|functie|stelling|career/)", re.I)
GUESS_PATHS = ["/vacatures", "/werken-bij", "/careers", "/jobs"]
# Link texts that say "a vacancy is here" but are not a job title.
GENERIC_LINK_TEXT = re.compile(
    r"^(vacatures?|vacancies|vacancy( -.*)?|bekijk( de)? vacature|lees meer|meer info(rmatie)?|apply( now)?"
    r"|solliciteer( direct| nu)?|read more|view( job)?|details|careers?|werken bij.*|alle vacatures"
    r"|open (vacatures|positions)|general interest application|open sollicitatie)$", re.I)
NON_JOB_TEXT = re.compile(r"cookie|privacy|linkedin|facebook|instagram|youtube|twitter", re.I)
NON_COMPANY_HOSTS = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
                     "youtube.com", "google.com")


@dataclass
class Page:
    url: str
    status: int
    text: str = ""
    title: str = ""
    h1: str = ""
    lang: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)   # (absolute url, anchor text)
    error: str = ""
    embeds: list[str] = field(default_factory=list)   # job-board addresses anywhere in the HTML

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.text)


def parse_html(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")
    lang = (soup.html.get("lang", "") if soup.html else "") or ""
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.h1.get_text(" ", strip=True)[:150] if soup.h1 else ""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        links.append((urljoin(url, href).split("#")[0], a.get_text(" ", strip=True)[:120]))
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return Page(url=url, status=200, text=text, title=title, h1=h1, lang=lang.lower()[:5], links=links,
                embeds=jobboards.board_urls(html))


class Fetcher:
    """HTTP fetcher with robots.txt, per-host politeness and a disk cache."""

    def __init__(self, cache_dir: Path | None = None, delay_secs: float = 1.0, use_cache: bool = True,
                 session: requests.Session | None = None):
        self.cache_dir = cache_dir or data_dir() / "crawl_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay_secs
        self.use_cache = use_cache
        self.http = session or requests.Session()
        self.http.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl,en;q=0.8"})
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")

    def allowed(self, url: str) -> bool:
        host = urlparse(url).scheme + "://" + urlparse(url).netloc
        if host not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.http.get(host + "/robots.txt", timeout=TIMEOUT)
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[host] = rp
        rp = self._robots[host]
        return rp.can_fetch(USER_AGENT, url) if rp else True

    def get(self, url: str) -> Page:
        cache = self._cache_path(url)
        if self.use_cache and cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            data["links"] = [tuple(x) for x in data.get("links", [])]
            return Page(**data)
        if not self.allowed(url):
            return Page(url=url, status=0, error="blocked_by_robots")
        host = urlparse(url).netloc
        wait = self.delay - (time.monotonic() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()
        try:
            resp = self.http.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
            body = resp.raw.read(MAX_BYTES, decode_content=True)
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or "html" not in ctype:
                page = Page(url=resp.url, status=resp.status_code, error=f"content-type:{ctype[:40]}")
            else:
                html = body.decode(resp.encoding or "utf-8", errors="replace")
                page = parse_html(resp.url, html)
        except Exception as exc:   # noqa: BLE001 - one bad site must never stop a crawl
            # Includes errors raised while streaming the body (urllib3 read timeouts, broken
            # connections) and parser errors. Not cached, so a later run retries them.
            return Page(url=url, status=0, error=type(exc).__name__)
        cache.write_text(json.dumps(page.__dict__, ensure_ascii=False), encoding="utf-8")
        return page

    def get_json(self, url: str):
        """A public JSON feed (job boards). Same robots.txt rules, politeness and cache; None on any failure."""
        cache = self._cache_path("json:" + url)
        if self.use_cache and cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        if not self.allowed(url):
            return None
        host = urlparse(url).netloc
        wait = self.delay - (time.monotonic() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()
        try:
            resp = self.http.get(url, timeout=TIMEOUT, headers={"Accept": "application/json"})
            if resp.status_code != 200 or len(resp.content) > 4 * MAX_BYTES:
                return None
            data = resp.json()
        except Exception:   # noqa: BLE001 - a missing or broken feed is the same as no feed
            return None
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data


class BrowserPool:
    """One shared Crawl4AI browser for all worker threads, running on its own event loop."""

    _instance: "BrowserPool | None" = None
    _lock = threading.Lock()

    def __init__(self, tabs: int = 4):
        os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")
        from crawl4ai import AsyncWebCrawler, BrowserConfig  # noqa: F401 - fail early if missing
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.tabs = tabs
        self.crawler = asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(timeout=120)
        atexit.register(self.close)

    async def _start(self):
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        self.sem = asyncio.Semaphore(self.tabs)
        crawler = AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=USER_AGENT, verbose=False))
        await crawler.start()
        return crawler

    @classmethod
    def get(cls) -> "BrowserPool":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    async def _fetch(self, url: str):
        from crawl4ai import CacheMode, CrawlerRunConfig
        async with self.sem:
            return await self.crawler.arun(url=url, config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS, page_timeout=30000, wait_until="domcontentloaded",
                delay_before_return_html=1.5, verbose=False))

    def fetch(self, url: str) -> Page:
        try:
            result = asyncio.run_coroutine_threadsafe(self._fetch(url), self.loop).result(timeout=90)
        except Exception as exc:  # noqa: BLE001
            return Page(url=url, status=0, error=f"browser:{type(exc).__name__}")
        if not getattr(result, "success", False) or not getattr(result, "html", None):
            return Page(url=url, status=getattr(result, "status_code", 0) or 0,
                        error=f"browser:{(getattr(result, 'error_message', '') or 'no html')[:60]}")
        page = parse_html(getattr(result, "url", None) or url, result.html)
        page.status = getattr(result, "status_code", 200) or 200
        return page

    def close(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.crawler.close(), self.loop).result(timeout=30)
        except Exception:  # noqa: BLE001
            pass


class HybridFetcher(Fetcher):
    """Plain HTTP first (fast, free). Crawl4AI's browser when a site blocks or fails the request,
    or returns an almost empty page (JavaScript sites). Same robots.txt rules and cache."""

    MIN_TEXT = 300

    def get(self, url: str) -> Page:
        page = super().get(url)
        if page.error == "blocked_by_robots" or (page.ok and len(page.text) >= self.MIN_TEXT):
            return page
        rendered = self.render(url)
        return rendered if rendered.ok else page

    def render(self, url: str) -> Page:
        """Fetch through the browser (used directly for careers pages whose job list needs JS)."""
        cache = self._cache_path("browser:" + url)
        if self.use_cache and cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            data["links"] = [tuple(x) for x in data.get("links", [])]
            return Page(**data)
        if not self.allowed(url):
            return Page(url=url, status=0, error="blocked_by_robots")
        page = BrowserPool.get().fetch(url)
        if page.status != 0:
            cache.write_text(json.dumps(page.__dict__, ensure_ascii=False), encoding="utf-8")
        return page


def browser_available() -> bool:
    try:
        import crawl4ai  # noqa: F401
        return True
    except ImportError:
        return False


def default_fetcher(use_cache: bool = True) -> Fetcher:
    """HybridFetcher when Crawl4AI is installed (pip install -e '.[crawl]'), plain HTTP otherwise.
    use_cache=False reads every page again (signals such as open jobs go stale) and renews the cache."""
    return HybridFetcher(use_cache=use_cache) if browser_available() else Fetcher(use_cache=use_cache)


@dataclass
class SiteCrawl:
    home: Page
    careers: Page | None = None
    jobs: list[Page] = field(default_factory=list)
    job_link_count: int = 0      # vacancies linked from the careers page (we fetch at most max_jobs)
    job_titles: list[str] = field(default_factory=list)
    board_url: str = ""          # the company's hosted job board, when its feed was read (job_boards)

    @property
    def pages(self) -> list[Page]:
        return [p for p in [self.home, self.careers, *self.jobs] if p is not None]


def same_site(url: str, base: str) -> bool:
    a, b = urlparse(url).netloc.lower(), urlparse(base).netloc.lower()
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    a, b = strip(a), strip(b)
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def find_careers_link(page: Page) -> str | None:
    """Prefer links whose anchor text or path looks like a careers page. External job boards
    (werkenbij-sites on another domain) are allowed: many Dutch firms use one."""
    scored = []
    for url, text in page.links:
        hay = f"{urlparse(url).path} {text}"
        if CAREERS_HINTS.search(hay):
            score = 2 if CAREERS_HINTS.search(text) else 1
            scored.append((score, -len(url), url))
    return max(scored)[2] if scored else None


def _job_links(page: Page) -> list[str]:
    return [u for u, _ in page.links
            if JOB_LINK_HINTS.search(urlparse(u).path) and len(urlparse(u).path.strip("/").split("/")) >= 2]


def crawl_site(fetcher: Fetcher, website: str, max_jobs: int = 5, job_boards: dict | None = None) -> SiteCrawl:
    """Home page, careers page and a few vacancy pages. With `job_boards` (scoring.yaml), the open
    jobs of a hosted job board linked or embedded on the site are added from its public feed."""
    site = _crawl_pages(fetcher, website, max_jobs)
    if job_boards and site.home.ok and hasattr(fetcher, "get_json"):
        _add_board_jobs(fetcher, site, job_boards)
    return site


def _add_board_jobs(fetcher: Fetcher, site: SiteCrawl, job_boards: dict) -> None:
    careers = site.careers if site.careers and site.careers.ok else None
    # Most trusted first: the careers page itself, what it embeds and links to, then the home page.
    urls = ([careers.url, *careers.embeds, *(u for u, _ in careers.links)] if careers else []) + \
           [*site.home.embeds, *(u for u, _ in site.home.links)]
    board = jobboards.find_board(urls)
    if not board:
        return
    jobs = jobboards.parse_feed(board.name, fetcher.get_json(board.feed))
    if not jobs:
        return
    site.board_url = board.page
    site.job_titles = list(dict.fromkeys(jobboards.titles(jobs, job_boards.get("countries")) + site.job_titles))
    site.job_link_count = max(site.job_link_count, len(jobs))


def _crawl_pages(fetcher: Fetcher, website: str, max_jobs: int = 5) -> SiteCrawl:
    # LinkedIn often stores http:// addresses. Try https:// first (nearly every site has it, and
    # some networks only allow HTTPS), then fall back to the address as given.
    bare = re.sub(r"^https?://", "", website.strip(), flags=re.I)
    home = fetcher.get("https://" + bare)
    if not home.ok and website.lower().startswith("http://"):
        home = fetcher.get("http://" + bare)
    site = SiteCrawl(home=home)
    if not home.ok:
        return site

    careers_url = find_careers_link(home)
    if careers_url:
        site.careers = fetcher.get(careers_url)
    else:
        root = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}"
        for path in GUESS_PATHS[:2]:
            page = fetcher.get(root + path)
            if page.ok:
                site.careers = page
                break
    if not site.careers or not site.careers.ok:
        return site
    # Many careers pages load their job list with JavaScript: if plain HTTP shows no job links,
    # look again through the browser.
    if hasattr(fetcher, "render") and not _job_links(site.careers):
        rendered = fetcher.render(site.careers.url)
        if rendered.ok and _job_links(rendered):
            site.careers = rendered

    seen, job_urls, titles = set(), [], []
    for url, text in site.careers.links:
        url = url.rstrip("/")
        host = urlparse(url).netloc.lower()
        if url in seen or url == site.careers.url.rstrip("/") or NON_JOB_TEXT.search(text or ""):
            continue
        if any(host == h or host.endswith("." + h) for h in NON_COMPANY_HOSTS):
            continue
        path = urlparse(url).path
        if JOB_LINK_HINTS.search(path) and len(path.strip("/").split("/")) >= 2:
            seen.add(url)
            job_urls.append(url)
            if text and len(text) > 3 and not GENERIC_LINK_TEXT.match(text.strip()):
                titles.append(text.strip())
    site.job_link_count = len(job_urls)
    for url in job_urls[:max_jobs]:
        page = fetcher.get(url)
        site.jobs.append(page)
        if page.ok and page.h1 and not GENERIC_LINK_TEXT.match(page.h1):
            titles.append(page.h1)
    # Unique titles, order kept
    site.job_titles = list(dict.fromkeys(titles))
    return site
