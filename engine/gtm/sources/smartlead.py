"""Smartlead REST API (https://server.smartlead.ai/api/v1).

The key goes in the URL (?api_key=...), so a cloud proxy cannot add it as a header: run Layer 6
where the key is set for real (for example a laptop with .env). The key is never logged and is
scrubbed from every error message. Each client can name its own variable (sending.yaml api_key_env),
so a client with its own Smartlead account never falls back to another client's key. 429 and 5xx responses are retried with backoff.

The public docs disagree on POST vs PATCH for /status and /settings; the client tries the
documented method and falls back to the other on 404/405.
"""

from __future__ import annotations

import os
import re
import time

import requests

API = "https://server.smartlead.ai/api/v1"


class SmartleadError(RuntimeError):
    pass


def scrub(text: str) -> str:
    return re.sub(r"(api_key=)[^&\s\"']+", r"\1[redacted]", text)


class SmartleadClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 retries: int = 3, backoff_secs: float = 2.0, key_env: str = "SMARTLEAD_API_KEY"):
        key = api_key or os.environ.get(key_env)
        if not key or key == "proxy-injected":
            raise SmartleadError(f"{key_env} is not set. Smartlead takes the key in the URL, so run Layer 6 "
                                 "where the real key is set (the cloud proxy cannot add it).")
        self.key = key
        self.http = session or requests.Session()
        self.retries, self.backoff = retries, backoff_secs

    def _req(self, method: str, path: str, json=None, params=None, alt_method: str | None = None):
        query = {"api_key": self.key, **(params or {})}
        attempt = 0
        while True:
            try:
                resp = self.http.request(method, f"{API}{path}", params=query, json=json, timeout=60)
            except requests.RequestException as exc:
                raise SmartleadError(f"Smartlead {method} {path} failed: {type(exc).__name__}") from None
            if resp.status_code in (404, 405) and alt_method:
                method, alt_method = alt_method, None
                continue
            if resp.status_code in (429, 500, 502, 503) and attempt < self.retries:
                attempt += 1
                time.sleep(self.backoff * 2 ** (attempt - 1))
                continue
            if resp.status_code >= 400:
                raise SmartleadError(f"Smartlead {method} {path} -> {resp.status_code}: {scrub(resp.text[:300])}")
            return resp.json() if resp.text else {}

    # campaigns
    def create_campaign(self, name: str) -> int:
        data = self._req("POST", "/campaigns/create", json={"name": name})
        cid = (data.get("campaign") or {}).get("id") or data.get("id")
        if not cid:
            raise SmartleadError("Smartlead did not return a campaign id.")
        return int(cid)

    def save_sequences(self, campaign_id: int, sequences: list[dict]) -> dict:
        return self._req("POST", f"/campaigns/{campaign_id}/sequences", json={"sequences": sequences})

    def set_schedule(self, campaign_id: int, schedule: dict) -> dict:
        return self._req("POST", f"/campaigns/{campaign_id}/schedule", json=schedule)

    def update_settings(self, campaign_id: int, settings: dict) -> dict:
        return self._req("PATCH", f"/campaigns/{campaign_id}/settings", json=settings, alt_method="POST")

    def set_status(self, campaign_id: int, status: str) -> dict:
        return self._req("POST", f"/campaigns/{campaign_id}/status", json={"status": status}, alt_method="PATCH")

    def link_email_accounts(self, campaign_id: int, account_ids: list[int]) -> dict:
        return self._req("POST", f"/campaigns/{campaign_id}/email-accounts", json={"email_account_ids": account_ids})

    # email accounts
    def email_accounts(self) -> list[dict]:
        data = self._req("GET", "/email-accounts", params={"limit": 100})
        return data if isinstance(data, list) else data.get("data", data.get("email_accounts", []))

    # leads
    def add_leads(self, campaign_id: int, leads: list[dict]) -> dict:
        if len(leads) > 400:
            raise SmartleadError("At most 400 leads per import.")
        return self._req("POST", f"/campaigns/{campaign_id}/leads", json={
            "lead_list": leads,
            "settings": {"ignore_global_block_list": False, "ignore_unsubscribe_list": False,
                         "ignore_duplicate_leads_in_other_campaign": False}})

    def leads(self, campaign_id: int, **filters) -> list[dict]:
        out, offset = [], 0
        while True:
            page = self._req("GET", f"/campaigns/{campaign_id}/leads",
                             params={"offset": offset, "limit": 100, **filters})
            items = page.get("data", page.get("leads", [])) if isinstance(page, dict) else page
            out.extend(items)
            if len(items) < 100:
                return out
            offset += 100

    def message_history(self, campaign_id: int, lead_id: int) -> list[dict]:
        for path in (f"/campaigns/{campaign_id}/leads/{lead_id}/message-history",
                     f"/campaigns/{campaign_id}/leads/{lead_id}/activity"):
            try:
                data = self._req("GET", path)
            except SmartleadError as exc:
                if "-> 404" in str(exc):
                    continue
                raise
            if isinstance(data, list):
                return data
            return data.get("history") or data.get("events") or data.get("data") or []
        return []

    def block(self, emails: list[str]) -> dict:
        return self._req("POST", "/leads/block-list", json={"emails": emails})
