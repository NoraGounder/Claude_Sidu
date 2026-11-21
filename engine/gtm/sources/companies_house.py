"""Companies House public data API (https://developer.company-information.service.gov.uk), free.

Used by the ETA search to find UK companies, read their profile, owners (persons with significant
control), directors and filed accounts. Authentication is HTTP Basic with the API key as the user name and
an empty password. In a Claude Code cloud session the network proxy injects the real key for
api.company-information.service.gov.uk and document-api.company-information.service.gov.uk, so set
COMPANIES_HOUSE_API_KEY to any placeholder there. The key is never printed.

Rate limit: 600 requests per 5 minutes per key. The client paces itself under a configurable ceiling,
retries 429 and 5xx with backoff, and counts every request so a run can stop at its own cap.
"""

from __future__ import annotations

import os
import time
from collections import deque
from urllib.parse import urlparse

import requests

API = "https://api.company-information.service.gov.uk"
DOCS = "https://document-api.company-information.service.gov.uk"
WINDOW_SECS = 300
PROXY_PLACEHOLDER = "proxy-injected"


class CompaniesHouseError(RuntimeError):
    pass


class RequestCapReached(CompaniesHouseError):
    """The run used the number of requests it was allowed (limits.yaml companies_house.max_requests_per_run)."""


class CompaniesHouseClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 per_window: int = 550, max_requests: int | None = None, retries: int = 4,
                 backoff_secs: float = 5.0, sleep=time.sleep, clock=time.monotonic):
        key = api_key or os.environ.get("COMPANIES_HOUSE_API_KEY")
        if not key:
            raise CompaniesHouseError(
                "COMPANIES_HOUSE_API_KEY is not set. Get a free key at developer.company-information.service.gov.uk "
                "(in a cloud session save it as a network secret and set the variable to 'proxy-injected').")
        self.http = session or requests.Session()
        if key != PROXY_PLACEHOLDER:
            # A real key (laptop): Basic auth, key as user name, empty password. In a cloud session the
            # variable holds the placeholder and the network proxy adds the header itself.
            self.http.auth = (key, "")
        self.http.headers.update({"Accept": "application/json", "User-Agent": "eta-search/0.1"})
        self.per_window, self.max_requests = per_window, max_requests
        self.retries, self.backoff = retries, backoff_secs
        self._sleep, self._clock = sleep, clock
        self._recent: deque[float] = deque()
        self.requests_made = 0

    # ---------- plumbing ----------

    def _pace(self) -> None:
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise RequestCapReached(f"Request cap of {self.max_requests} for this run reached.")
        now = self._clock()
        while self._recent and now - self._recent[0] > WINDOW_SECS:
            self._recent.popleft()
        if len(self._recent) >= self.per_window:
            wait = WINDOW_SECS - (now - self._recent[0]) + 1
            self._sleep(max(wait, 1))
        self._recent.append(self._clock())
        self.requests_made += 1

    def _get(self, url: str, params: dict | None = None, accept: str | None = None,
             allow_404: bool = False) -> requests.Response | None:
        attempt = 0
        while True:
            self._pace()
            headers = {"Accept": accept} if accept else None
            try:
                resp = self.http.get(url, params=params, headers=headers, timeout=60)
            except requests.RequestException as exc:
                if attempt < self.retries:
                    attempt += 1
                    self._sleep(self.backoff * 2 ** (attempt - 1))
                    continue
                raise CompaniesHouseError(f"Companies House request failed: {type(exc).__name__}") from None
            if resp.status_code == 404 and allow_404:
                return None
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                attempt += 1
                self._sleep(self.backoff * 2 ** (attempt - 1))
                continue
            if resp.status_code == 401:
                raise CompaniesHouseError("Companies House rejected the API key (401 Invalid Authorization). "
                                          "Check the key, and that it is a REST API key with no IP restriction.")
            if resp.status_code >= 400:
                raise CompaniesHouseError(f"Companies House {urlparse(url).path} -> {resp.status_code}: "
                                          f"{resp.text[:200]}")
            return resp

    def _json(self, path: str, params: dict | None = None, allow_404: bool = False) -> dict | None:
        resp = self._get(f"{API}{path}", params=params, allow_404=allow_404)
        return None if resp is None else resp.json()

    # ---------- endpoints ----------

    def advanced_search(self, sic_codes: list[str] | None = None, company_status: str | None = "active",
                        company_type: str | None = "ltd", incorporated_from: str | None = None,
                        incorporated_to: str | None = None, location: str | None = None,
                        size: int = 500, start_index: int = 0) -> dict:
        """Companies matching the filters: {items: [...], hits: int}. Empty result -> 404 -> no items."""
        params = {"size": size, "start_index": start_index}
        if sic_codes:
            params["sic_codes"] = ",".join(str(c) for c in sic_codes)
        for key, value in (("company_status", company_status), ("company_type", company_type),
                           ("incorporated_from", incorporated_from), ("incorporated_to", incorporated_to),
                           ("location", location)):
            if value:
                params[key] = value
        data = self._json("/advanced-search/companies", params=params, allow_404=True)
        return data or {"items": [], "hits": 0}

    def profile(self, number: str) -> dict | None:
        return self._json(f"/company/{number}", allow_404=True)

    def officers(self, number: str) -> list[dict]:
        data = self._json(f"/company/{number}/officers", params={"items_per_page": 100}, allow_404=True)
        return (data or {}).get("items", [])

    def pscs(self, number: str) -> list[dict]:
        data = self._json(f"/company/{number}/persons-with-significant-control",
                          params={"items_per_page": 100}, allow_404=True)
        return (data or {}).get("items", [])

    def accounts_filings(self, number: str, limit: int = 10) -> list[dict]:
        data = self._json(f"/company/{number}/filing-history",
                          params={"category": "accounts", "items_per_page": limit}, allow_404=True)
        return (data or {}).get("items", [])

    def document_formats(self, metadata_url: str) -> dict:
        """Document metadata: {'resources': {'application/xhtml+xml': {...}, 'application/pdf': {...}}}."""
        resp = self._get(_doc_url(metadata_url))
        return resp.json()

    def document_content(self, metadata_url: str, mime: str = "application/xhtml+xml") -> bytes:
        """The filed document itself. The API answers with a redirect to a signed storage URL, which
        requests follows without sending the Authorization header to the other host."""
        resp = self._get(_doc_url(metadata_url) + "/content", accept=mime)
        return resp.content


def _doc_url(metadata_url: str) -> str:
    """Filing history links point at frontend-doc-api; the documented host is document-api."""
    path = urlparse(metadata_url).path if metadata_url.startswith("http") else metadata_url
    return f"{DOCS}{path}"
