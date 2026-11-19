"""HubSpot CRM (free plan) through its REST API (https://api.hubapi.com).

Authentication is a private app token sent as `Authorization: Bearer ...` (HUBSPOT_TOKEN). Because
it is a header, a Claude Code cloud session can have the proxy inject it ("proxy-injected").
Layer 7 only creates and updates companies, contacts and deals; it never deletes anything.
"""

from __future__ import annotations

import os
import time

import requests

API = "https://api.hubapi.com"

# HubSpot-defined association type ids (v3/v4 "associations" on create).
DEAL_TO_CONTACT = 3
DEAL_TO_COMPANY = 5
CONTACT_TO_COMPANY = 279


class HubSpotError(RuntimeError):
    pass


class HubSpotClient:
    def __init__(self, token: str | None = None, session: requests.Session | None = None,
                 retries: int = 3, backoff_secs: float = 2.0, token_env: str = "HUBSPOT_TOKEN"):
        token = token or os.environ.get(token_env)
        if not token:
            raise HubSpotError(f"{token_env} is not set (a HubSpot private app token with CRM object "
                               "read and write scopes; in a cloud session save it as a network secret).")
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.retries, self.backoff = retries, backoff_secs

    def _req(self, method: str, path: str, json=None) -> dict:
        attempt = 0
        while True:
            try:
                resp = self.http.request(method, f"{API}{path}", json=json, timeout=60)
            except requests.RequestException as exc:
                raise HubSpotError(f"HubSpot {method} {path} failed: {type(exc).__name__}") from None
            if resp.status_code in (429, 500, 502, 503) and attempt < self.retries:
                attempt += 1
                time.sleep(self.backoff * 2 ** (attempt - 1))
                continue
            if resp.status_code >= 400:
                raise HubSpotError(f"HubSpot {method} {path} -> {resp.status_code}: {resp.text[:300]}")
            return resp.json() if resp.text else {}

    def find(self, obj: str, prop: str, value: str) -> str | None:
        data = self._req("POST", f"/crm/v3/objects/{obj}/search", json={
            "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
            "limit": 1})
        results = data.get("results") or []
        return str(results[0]["id"]) if results else None

    def create(self, obj: str, properties: dict, associations: list[tuple[str, int]] | None = None) -> str:
        body: dict = {"properties": {k: v for k, v in properties.items() if v not in (None, "")}}
        if associations:
            body["associations"] = [
                {"to": {"id": to_id},
                 "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}]}
                for to_id, type_id in associations]
        data = self._req("POST", f"/crm/v3/objects/{obj}", json=body)
        if not data.get("id"):
            raise HubSpotError(f"HubSpot did not return an id for the new {obj[:-1]}.")
        return str(data["id"])

    def update(self, obj: str, object_id: str, properties: dict) -> None:
        self._req("PATCH", f"/crm/v3/objects/{obj}/{object_id}",
                  json={"properties": {k: v for k, v in properties.items() if v is not None}})
