"""OpenRouter client for structured AI decisions (default model: TypeSafe's Jev Router).

Auth is a Bearer token from OPENROUTER_API_KEY. In a Claude Code cloud session set it to any
dummy value and save the real key as a network secret for openrouter.ai.

Every call asks for strict JSON matching a schema and for OpenRouter's usage accounting, so the
real cost of each call lands in the runs ledger.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

API = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "typesafe/jev-router"


class OpenRouterError(RuntimeError):
    pass


@dataclass
class Decision:
    data: dict
    cost_usd: float
    model_used: str


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set. See .env.example.")
        self.http = session or requests.Session()
        self.http.headers.update({
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://quailworks.xyz",
            "X-Title": "Quailworks lead engine",
        })

    def decide(self, model: str, system: str, user: str, schema_name: str, schema: dict,
               timeout: int = 120) -> Decision:
        body = {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            "usage": {"include": True},
        }
        resp = self.http.post(API, json=body, timeout=timeout)
        if resp.status_code >= 400:
            raise OpenRouterError(f"OpenRouter {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        if payload.get("error"):
            raise OpenRouterError(f"OpenRouter error: {payload['error']}")
        try:
            content = payload["choices"][0]["message"]["content"]
            data = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise OpenRouterError(f"Answer was not valid JSON: {str(payload)[:300]}") from exc
        usage = payload.get("usage") or {}
        return Decision(data=data, cost_usd=float(usage.get("cost") or 0.0),
                        model_used=payload.get("model", model))
