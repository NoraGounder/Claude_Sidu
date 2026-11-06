"""MillionVerifier single-email API, used only to re-check emails older than the freshness window.

The API takes the key as a URL parameter (?api=...), so the cloud proxy cannot inject it as a
header: run this step where MILLIONVERIFIER_API_KEY is set (for example a laptop with .env).
The key is never logged; error text is scrubbed.
"""

from __future__ import annotations

import os
import re

import requests

API = "https://api.millionverifier.com/api/v3/"


class MillionVerifierError(RuntimeError):
    pass


def _scrub(text: str) -> str:
    return re.sub(r"(api=)[^&\s]+", r"\1[redacted]", text)


class MillionVerifierClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.key = api_key or os.environ.get("MILLIONVERIFIER_API_KEY")
        if not self.key or self.key == "proxy-injected":
            raise MillionVerifierError("MILLIONVERIFIER_API_KEY is not set. This step needs the real key "
                                       "locally (the key goes in the URL, so the cloud proxy cannot add it).")
        self.http = session or requests.Session()

    def verify(self, email: str, timeout: int = 20) -> dict:
        try:
            resp = self.http.get(API, params={"api": self.key, "email": email, "timeout": timeout},
                                 timeout=timeout + 10)
        except requests.RequestException as exc:
            raise MillionVerifierError(f"MillionVerifier request failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise MillionVerifierError(f"MillionVerifier HTTP {resp.status_code}: {_scrub(resp.text[:200])}")
        data = resp.json()
        if data.get("error"):
            raise MillionVerifierError(f"MillionVerifier error: {_scrub(str(data['error']))}")
        return {"result": (data.get("result") or "unknown").lower(), "role": bool(data.get("role")),
                "free": bool(data.get("free"))}
