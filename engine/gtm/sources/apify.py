"""Minimal Apify client: start an actor run, wait for it, read its dataset.

Auth is a Bearer token from APIFY_TOKEN. In a Claude Code cloud session, set APIFY_TOKEN to any
dummy value and save the real token as a network secret for api.apify.com; the proxy swaps it in.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

API = "https://api.apify.com/v2"
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


class ApifyError(RuntimeError):
    pass


@dataclass
class RunResult:
    items: list[dict]
    run_id: str | None
    status: str
    cost_usd: float | None


class ApifyClient:
    def __init__(self, token: str | None = None, session: requests.Session | None = None):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise ApifyError("APIFY_TOKEN is not set. See .env.example.")
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {self.token}"})

    def run_actor(self, actor: str, actor_input: dict, wait_secs: int = 900, poll_secs: int = 5) -> RunResult:
        actor_path = actor.replace("/", "~")
        resp = self.http.post(f"{API}/acts/{actor_path}/runs", json=actor_input, timeout=60)
        if resp.status_code >= 400:
            raise ApifyError(f"Starting {actor} failed ({resp.status_code}): {resp.text[:300]}")
        run = resp.json()["data"]
        run_id = run["id"]

        deadline = time.monotonic() + wait_secs
        while run["status"] not in TERMINAL:
            if time.monotonic() > deadline:
                raise ApifyError(f"Run {run_id} of {actor} did not finish within {wait_secs}s.")
            time.sleep(poll_secs)
            resp = self.http.get(f"{API}/actor-runs/{run_id}", timeout=60)
            resp.raise_for_status()
            run = resp.json()["data"]

        items: list[dict] = []
        dataset_id = run.get("defaultDatasetId")
        if dataset_id:
            offset = 0
            while True:
                resp = self.http.get(
                    f"{API}/datasets/{dataset_id}/items",
                    params={"clean": "true", "format": "json", "offset": offset, "limit": 1000},
                    timeout=120,
                )
                resp.raise_for_status()
                page = resp.json()
                items.extend(page)
                if len(page) < 1000:
                    break
                offset += len(page)

        cost = run.get("usageTotalUsd")
        return RunResult(items=items, run_id=run_id, status=run["status"],
                         cost_usd=float(cost) if cost is not None else None)


def load_fixture(path: str | Path) -> RunResult:
    """Read saved actor output instead of calling Apify (tests and offline development)."""
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    return RunResult(items=items, run_id=None, status="FIXTURE", cost_usd=0.0)
