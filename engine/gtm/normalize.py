"""Small, defensive helpers for cleaning vendor data."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

COUNTRY_CODES = {
    "netherlands": "NL", "nederland": "NL", "the netherlands": "NL", "nl": "NL",
    "belgium": "BE", "belgië": "BE", "belgie": "BE", "belgique": "BE", "be": "BE",
    # Short-mode LinkedIn locations are "City, Province" with no country. Provinces that exist in
    # only one country (Limburg is in both, so it is left out).
    "noord-holland": "NL", "north holland": "NL", "zuid-holland": "NL", "south holland": "NL",
    "noord-brabant": "NL", "north brabant": "NL", "gelderland": "NL", "overijssel": "NL",
    "zeeland": "NL", "friesland": "NL", "fryslân": "NL", "groningen": "NL", "drenthe": "NL",
    "flevoland": "NL", "utrecht": "NL",
    "flemish region": "BE", "vlaanderen": "BE", "flanders": "BE", "antwerpen": "BE", "antwerp": "BE",
    "oost-vlaanderen": "BE", "west-vlaanderen": "BE", "vlaams-brabant": "BE", "flemish brabant": "BE",
    "brussels": "BE", "bruxelles": "BE", "wallonia": "BE", "wallonie": "BE", "hainaut": "BE",
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "united kingdom": "GB", "uk": "GB", "gb": "GB",
    "france": "FR", "fr": "FR",
}

# Hosts that are never a company's own website.
NON_COMPANY_HOSTS = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
                     "youtube.com", "google.com", "bit.ly", "linktr.ee")


def pick(item: dict, *paths: str) -> Any:
    """Return the first non-empty value among dotted paths, e.g. pick(d, 'website', 'links.website')."""
    for path in paths:
        value: Any = item
        for part in path.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                value = None
            if value is None:
                break
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_domain(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or any(host == h or host.endswith("." + h) for h in NON_COMPANY_HOSTS):
        return None
    return host


def normalize_linkedin_company_url(url: str | None) -> str | None:
    if not url or "linkedin.com" not in url:
        return None
    match = re.search(r"linkedin\.com/(company|school|showcase)/([^/?#]+)", url, re.I)
    if not match:
        return None
    return f"https://www.linkedin.com/{match.group(1).lower()}/{match.group(2).lower()}/"


def country_code(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, dict):
        value = pick(value, "countryCode", "country", "geographicArea")
    text = str(value).strip().lower()
    if text in COUNTRY_CODES:
        return COUNTRY_CODES[text]
    for name, code in COUNTRY_CODES.items():
        if len(name) > 2 and name in text:
            return code
    return text.upper() if len(text) == 2 else None


def size_range(value: Any) -> tuple[int | None, int | None]:
    """Company's stated size band. Accepts {'start': 51, 'end': 200}, '51-200 employees', '10,001+'."""
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, dict):
        start, end = value.get("start"), value.get("end")
        return (int(start) if start else None), (int(end) if end else None)
    if isinstance(value, (int, float)):
        return None, None
    numbers = [int(n) for n in re.findall(r"\d+", str(value).replace(".", "").replace(",", ""))]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return numbers[0], None
    return None, None


def member_count(value: Any) -> int | None:
    """LinkedIn member count: a plain number, often lower than the real headcount."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def has_keyword(name: str, keywords: list[str]) -> str | None:
    low = name.lower()
    for kw in keywords:
        if kw.lower() in low:
            return kw
    return None
