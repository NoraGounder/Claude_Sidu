"""TypeSafe Jev 1.14 through OpenRouter's Decisions API. The only AI decision-maker in the pipeline.

Policy (see clients/<client>/ai.yaml):
- model must be exactly typesafe/jev-1.14; routers, aliases and other models are refused
- the endpoint must be OpenRouter's /api/alpha/decisions
- no fallback: any failure, or an answer from a model other than Jev 1.14, raises JevUnavailable
- the API key is read from the environment and never printed; error text is scrubbed
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import requests

REQUIRED_MODEL = "typesafe/jev-1.14"
REQUIRED_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
FORBIDDEN_MODELS = ("openrouter/auto", "typesafe/jev-router", "~typesafe/jev-latest", "typesafe/jev-latest")


class JevPolicyError(RuntimeError):
    """The configuration breaks the AI policy. Nothing was called."""


class JevUnavailable(RuntimeError):
    """Jev failed or answered as another model. The run must stop; never switch models."""


def scrub(text: str) -> str:
    text = re.sub(r"sk-or-[A-Za-z0-9_\-]+", "[redacted-key]", text)
    text = re.sub(r"(keys/)[A-Za-z0-9]+", r"\1[redacted]", text)
    return re.sub(r"(Bearer\s+)\S+", r"\1[redacted]", text)


def check_policy(ai: dict) -> None:
    model = ai.get("model")
    if model in FORBIDDEN_MODELS:
        raise JevPolicyError(f"Model '{model}' is not allowed. Use {REQUIRED_MODEL} only.")
    if model != REQUIRED_MODEL:
        raise JevPolicyError(f"ai.yaml sets model '{model}'; the policy allows only {REQUIRED_MODEL}.")
    if ai.get("endpoint") != REQUIRED_ENDPOINT:
        raise JevPolicyError(f"ai.yaml endpoint must be {REQUIRED_ENDPOINT}.")
    if str(ai.get("fallback", "none")).lower() != "none":
        raise JevPolicyError("ai.yaml must set fallback: none. Jev failures stop the run.")


def is_jev_114(model_id: str | None) -> bool:
    """The API reports a dated snapshot, e.g. typesafe/jev-1.14-20261014."""
    return bool(model_id) and (model_id == REQUIRED_MODEL or model_id.startswith(REQUIRED_MODEL + "-"))


@dataclass
class JevResult:
    answers: dict
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    request_id: str | None


class JevClient:
    def __init__(self, ai: dict, session: requests.Session | None = None):
        check_policy(ai)
        key = os.environ.get(ai.get("api_key_env", "OPENROUTER_API_KEY"))
        if not key:
            raise JevPolicyError(f"{ai.get('api_key_env', 'OPENROUTER_API_KEY')} is not set "
                                 "(in a cloud session, set it to 'proxy-injected').")
        self.model = ai["model"]
        self.endpoint = ai["endpoint"]
        self.http = session or requests.Session()
        self.http.headers.update({
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://quailworks.co",
            "X-Title": "Quailworks lead engine",
        })

    def decide(self, state, questions: dict, timeout: int = 60) -> JevResult:
        body = {"model": self.model, "state": state, "questions": questions}
        started = time.monotonic()
        try:
            resp = self.http.post(self.endpoint, json=body, timeout=timeout)
        except requests.RequestException as exc:
            raise JevUnavailable(f"Jev request failed: {type(exc).__name__}") from None
        latency = int((time.monotonic() - started) * 1000)
        if resp.status_code != 200:
            raise JevUnavailable(f"Jev returned HTTP {resp.status_code}: {scrub(resp.text[:300])}")
        try:
            payload = resp.json()
        except ValueError:
            raise JevUnavailable("Jev returned a response that is not JSON.") from None
        model_id = payload.get("model")
        if not is_jev_114(model_id):
            raise JevUnavailable(f"Answer came from '{model_id}', not {REQUIRED_MODEL}. Stopping.")
        answers = payload.get("answers")
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise JevUnavailable("Jev's answers do not match the questions asked.")
        usage = payload.get("usage") or {}
        return JevResult(
            answers=answers, model_id=model_id,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=float(usage.get("cost") or 0.0), latency_ms=latency,
            request_id=payload.get("id"),
        )
