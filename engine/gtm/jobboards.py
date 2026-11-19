"""Open jobs from the public feeds of hosted job boards (Greenhouse, Lever, Ashby).

Many companies keep their vacancy list on a job board that draws the page with JavaScript, so a plain
crawl of the careers page finds no job titles. These boards publish the same list as a public JSON
feed, meant for embedding on company websites: exact titles and locations, no login, no scraping.
Opt-in per client (scoring.yaml `job_boards`); the feed is fetched by the polite, cached Fetcher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_SLUG = r"([A-Za-z0-9][A-Za-z0-9_.\-]*)"
# (board, pattern with the company's board name as group 1, feed URL)
PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?/?\?(?:[^\"'\s<>]*&)?for=" + _SLUG, re.I),
     "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("greenhouse", re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/(?!embed\b)" + _SLUG, re.I),
     "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", re.compile(r"https?://jobs\.lever\.co/" + _SLUG, re.I),
     "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("lever", re.compile(r"https?://jobs\.eu\.lever\.co/" + _SLUG, re.I),
     "https://api.eu.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/" + _SLUG, re.I),
     "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
]
BOARD_URL = re.compile(r"https?://[A-Za-z0-9.\-]*(?:greenhouse\.io|lever\.co|ashbyhq\.com)/[^\s\"'<>\\)]+", re.I)

COUNTRY_CODES = {
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
    "gb": "GB", "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB",
    "in": "IN", "india": "IN", "de": "DE", "germany": "DE", "fr": "FR", "france": "FR", "ca": "CA",
    "canada": "CA", "nl": "NL", "netherlands": "NL", "pl": "PL", "poland": "PL", "ie": "IE", "ireland": "IE",
    "au": "AU", "australia": "AU", "sg": "SG", "singapore": "SG", "jp": "JP", "japan": "JP", "il": "IL",
    "israel": "IL", "es": "ES", "spain": "ES", "it": "IT", "italy": "IT", "mx": "MX", "mexico": "MX",
    "br": "BR", "brazil": "BR", "cn": "CN", "china": "CN", "se": "SE", "sweden": "SE", "ch": "CH",
    "switzerland": "CH", "pt": "PT", "portugal": "PT", "ro": "RO", "romania": "RO", "ph": "PH",
    "philippines": "PH", "kr": "KR", "south korea": "KR", "tw": "TW", "taiwan": "TW",
}


@dataclass(frozen=True)
class Board:
    name: str
    slug: str
    feed: str
    page: str      # the board's public page, kept as the source of every title


def board_urls(html: str, limit: int = 20) -> list[str]:
    """Job-board addresses anywhere in a page's HTML (links, iframes, embed scripts)."""
    return list(dict.fromkeys(m.group(0) for m in BOARD_URL.finditer(html or "")))[:limit]


def find_board(urls: Iterable[str]) -> Board | None:
    """The first job board among these addresses (give the most trusted addresses first)."""
    for url in urls:
        for name, pattern, feed in PATTERNS:
            m = pattern.search(url or "")
            if m:
                slug = m.group(1).rstrip(".")
                page = {"greenhouse": f"https://job-boards.greenhouse.io/{slug}",
                        "lever": f"https://jobs.lever.co/{slug}",
                        "ashby": f"https://jobs.ashbyhq.com/{slug}"}[name]
                return Board(name, slug, feed.format(slug=slug), page)
    return None


def _country(value) -> str | None:
    return COUNTRY_CODES.get(str(value or "").strip().lower())


def parse_feed(board: str, data) -> list[dict]:
    """[{title, location, country}] from a feed. `country` is an ISO code when the board states it."""
    jobs: list[dict] = []
    if board == "greenhouse":
        for j in (data or {}).get("jobs") or []:
            jobs.append({"title": j.get("title"), "location": (j.get("location") or {}).get("name"), "country": None})
    elif board == "lever":
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            jobs.append({"title": j.get("text"), "location": cats.get("location"), "country": _country(j.get("country"))})
    elif board == "ashby":
        for j in (data or {}).get("jobs") or []:
            if j.get("isListed") is False:
                continue
            country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
            loc = ", ".join(x for x in dict.fromkeys([j.get("location"), country]) if x)
            jobs.append({"title": j.get("title"), "location": loc, "country": _country(country)})
    clean = []
    for j in jobs:
        title = re.sub(r"\s+", " ", str(j["title"] or "")).strip()
        if title:
            clean.append({"title": title[:120], "location": re.sub(r"\s+", " ", str(j["location"] or "")).strip()[:60],
                          "country": j["country"]})
    return clean


def titles(jobs: list[dict], countries: list[str] | None = None) -> list[str]:
    """Titles with their location, e.g. "Account Executive (Austin, TX)". Jobs whose board states a
    country outside `countries` are left out; jobs without a stated country are kept (the location
    stays in the title for the reader to judge)."""
    allowed = {c.upper() for c in countries or []}
    out = []
    for j in jobs:
        if allowed and j.get("country") and j["country"] not in allowed:
            continue
        out.append(f"{j['title']} ({j['location']})" if j.get("location") else j["title"])
    return list(dict.fromkeys(out))
