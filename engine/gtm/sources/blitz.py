"""BlitzAPI (https://api.blitz-api.ai/v2): companies by hiring signal, people by title, work emails.

The key travels in the `x-api-key` header, so in a Claude Code cloud session the network proxy can
inject it (set BLITZ_API_KEY to any placeholder there). The key is never logged. 429 and 503 are
retried with backoff. Every response reports `fair_usage` (records used and remaining on the plan);
a record is one company, person or email returned, and a miss costs nothing.
"""

from __future__ import annotations

import os
import time

import requests

API = "https://api.blitz-api.ai/v2"


class BlitzError(RuntimeError):
    pass


class BlitzClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 retries: int = 3, backoff_secs: float = 2.0):
        key = api_key or os.environ.get("BLITZ_API_KEY")
        if not key:
            raise BlitzError("BLITZ_API_KEY is not set (see .env.example; in a cloud session save the key as a "
                             "network secret for api.blitz-api.ai, header x-api-key).")
        self.http = session or requests.Session()
        self.http.headers.update({"x-api-key": key, "Content-Type": "application/json"})
        self.retries, self.backoff = retries, backoff_secs
        self.records_remaining: int | None = None

    def _post(self, path: str, body: dict) -> dict:
        attempt = 0
        while True:
            try:
                resp = self.http.post(f"{API}{path}", json=body, timeout=60)
            except requests.RequestException as exc:
                raise BlitzError(f"BlitzAPI {path} failed: {type(exc).__name__}") from None
            if resp.status_code in (429, 503) and attempt < self.retries:
                attempt += 1
                time.sleep(self.backoff * 2 ** (attempt - 1))
                continue
            if resp.status_code == 402:
                raise BlitzError("BlitzAPI: the plan's records are used up (402).")
            if resp.status_code >= 400:
                raise BlitzError(f"BlitzAPI {path} -> {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            remaining = (data.get("fair_usage") or {}).get("records_remaining")
            if remaining is not None:
                self.records_remaining = int(remaining)
            return data

    def companies_hiring(self, job: dict, company: dict, max_results: int = 50, cursor: str | None = None) -> dict:
        """Distinct companies with a matching job posting. Returns {results: [{company, matched_jobs}], cursor}."""
        body = {"job": job, "company": company, "max_results": max_results}
        if cursor:
            body["cursor"] = cursor
        return self._post("/company/tam-by-jobs", body)

    def people(self, company_linkedin_url: str, cascade: list[dict], max_results: int = 4) -> list[dict]:
        """Best-matching people at one company from ordered title tiers. Each: {icp, ranking, person}."""
        data = self._post("/search/waterfall-icp-keyword",
                          {"company_linkedin_url": company_linkedin_url, "cascade": cascade, "max_results": max_results})
        return data.get("results") or []

    def work_email(self, person_linkedin_url: str) -> str | None:
        """A verified work email for a LinkedIn profile, or None (a miss costs no record)."""
        data = self._post("/enrichment/email", {"person_linkedin_url": person_linkedin_url})
        return data.get("email") if data.get("found") else None
