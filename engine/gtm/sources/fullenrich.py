"""FullEnrich API (v2): people search and work-email enrichment (a waterfall over 20+ providers).

Auth: Bearer token from FULLENRICH_API_KEY. In a Claude Code cloud session set it to any dummy
value and save the real key as a network secret for app.fullenrich.com.

Costs (2026-11-06): people search 0.25 credit per person returned; work email 1 credit, charged
only when found. Pro plan: about $0.055 per credit.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

from gtm.sources.jev import scrub

API = "https://app.fullenrich.com/api/v2"


class FullEnrichError(RuntimeError):
    pass


@dataclass
class SearchResult:
    people: list[dict]
    credits: float
    total: int


class FullEnrichClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        key = api_key or os.environ.get("FULLENRICH_API_KEY")
        if not key:
            raise FullEnrichError("FULLENRICH_API_KEY is not set (cloud session: set it to 'proxy-injected').")
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    def _check(self, resp, what: str) -> dict:
        if resp.status_code >= 400:
            raise FullEnrichError(f"FullEnrich {what} failed ({resp.status_code}): {scrub(resp.text[:300])}")
        return resp.json()

    def credits(self) -> float | None:
        data = self._check(self.http.get(f"{API}/account/credits", timeout=30), "credit balance")
        return data.get("balance", data.get("credits"))

    def search_people(self, domain: str, titles: list[str], limit: int = 4) -> SearchResult:
        body = {
            "limit": limit,
            "current_company_domains": [{"value": domain, "exact_match": True, "exclude": False}],
            "current_position_titles": [{"value": t, "exact_match": False, "exclude": False} for t in titles],
        }
        data = self._check(self.http.post(f"{API}/people/search", json=body, timeout=60), "people search")
        meta = data.get("metadata") or {}
        return SearchResult(people=data.get("people") or [], credits=float(meta.get("credits") or 0),
                            total=int(meta.get("total") or 0))

    def start_enrichment(self, name: str, contacts: list[dict]) -> str:
        if len(contacts) > 100:
            raise FullEnrichError("At most 100 contacts per enrichment.")
        body = {"name": name, "data": contacts}
        data = self._check(self.http.post(f"{API}/contact/enrich/bulk", json=body, timeout=60), "enrichment start")
        if not data.get("enrichment_id"):
            raise FullEnrichError("FullEnrich did not return an enrichment_id.")
        return data["enrichment_id"]

    def wait_enrichment(self, enrichment_id: str, wait_secs: int = 900, poll_secs: int = 10) -> dict:
        deadline = time.monotonic() + wait_secs
        while True:
            data = self._check(self.http.get(f"{API}/contact/enrich/bulk/{enrichment_id}", timeout=60),
                               "enrichment result")
            status = data.get("status")
            if status == "FINISHED":
                return data
            if status in {"CANCELED", "CREDITS_INSUFFICIENT", "RATE_LIMIT", "UNKNOWN"}:
                raise FullEnrichError(f"Enrichment {enrichment_id} ended with status {status}.")
            if time.monotonic() > deadline:
                raise FullEnrichError(f"Enrichment {enrichment_id} still {status} after {wait_secs}s.")
            time.sleep(poll_secs)
