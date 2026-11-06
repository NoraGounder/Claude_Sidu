"""Polite, cheap website crawler for Layer 2.

- Plain HTTP first (requests + BeautifulSoup). Most company sites render on the server.
- Crawl4AI is used only when installed and a page comes back almost empty (JavaScript sites).
- Respects robots.txt, identifies itself, caps page size, and caches every page in
  data/crawl_cache/ so re-scoring never re-crawls.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from gtm.config import data_dir

USER_AGENT = "QuailworksBot/0.1 (+https://quailworks.xyz; company research)"
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
    return Page(url=url, status=200, text=text, title=title, h1=h1, lang=lang.lower()[:5], links=links)


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
                if len(page.text) < 300:
                    page = self._render(resp.url) or page
        except requests.RequestException as exc:
            # Network errors are not cached, so a later run retries them.
            return Page(url=url, status=0, error=type(exc).__name__)
        cache.write_text(json.dumps(page.__dict__, ensure_ascii=False), encoding="utf-8")
        return page

    def _render(self, url: str) -> Page | None:
        """JavaScript fallback through Crawl4AI, if installed (pip install -e '.[crawl]')."""
        try:
            import asyncio
            from crawl4ai import AsyncWebCrawler
        except ImportError:
            return None

        async def go():
            async with AsyncWebCrawler() as crawler:
                return await crawler.arun(url=url)

        try:
            result = asyncio.run(go())
        except Exception:
            return None
        if not getattr(result, "html", None):
            return None
        return parse_html(url, result.html)


@dataclass
class SiteCrawl:
    home: Page
    careers: Page | None = None
    jobs: list[Page] = field(default_factory=list)
    job_link_count: int = 0      # vacancies linked from the careers page (we fetch at most max_jobs)
    job_titles: list[str] = field(default_factory=list)

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


def crawl_site(fetcher: Fetcher, website: str, max_jobs: int = 5) -> SiteCrawl:
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
