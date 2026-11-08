"""The client's GTM brain (clients/<client>/brain.yaml): offer, personas, pains, message pillars,
competitors and signals in one place, in the structure of Pancake's GTM brains (gtmbrain.si).

`jev_context` turns it into a short, compact block for TypeSafe Jev 1.14 requests, so every
qualification, contact and angle decision sees the same task-specific context. Only `confirmed` and
`hypothesis` entries are sent (not those marked `jev: false`); `ask_mithun` entries stay out until
they are answered. No personal
data is ever part of the brain.
"""

from __future__ import annotations

import json
from typing import Any

from gtm.config import ClientConfig

USABLE = {"confirmed", "hypothesis"}
MAX_CHARS = 2500          # keeps each Jev request small (Jev bills input tokens)


def _texts(entries: list[dict] | None, field: str = "text") -> list[str]:
    return [e[field] for e in entries or []
            if e.get("status") in USABLE and e.get(field) and e.get("jev", True)]


def jev_context(cfg: ClientConfig, purpose: str) -> dict[str, Any]:
    """Seller context for one kind of Jev decision.

    purpose: "account" (Layer 2 buyer and ICP fit), "contact" (Layer 3 relevance of a job title),
    "angle" (Layer 5 opening and process choice), "reply" (Layer 6 reply classification).
    Returns {} when the client has no brain.yaml.
    """
    b = cfg.brain
    if not b:
        return {}
    ctx: dict[str, Any] = {"seller": _texts(b.get("market_profile")), "offer": _texts(b.get("offer"))}
    pains = {name: _texts(p.get("pains")) for name, p in (b.get("personas") or {}).items()}
    if purpose == "account":
        ctx["buyer_pains"] = sorted({t for v in pains.values() for t in v})
        ctx["alternatives_and_competitors"] = _texts(b.get("competitors"))
    elif purpose == "contact":
        ctx["pains_by_role"] = pains
    elif purpose == "angle":
        ctx["pains_by_role"] = pains
        ctx["message_pillars"] = _texts(b.get("message_pillars"))
        ctx["why_now_signals"] = {e["key"]: e["why_now"] for e in b.get("signals") or []
                                  if e.get("status") in USABLE}
    elif purpose == "reply":
        ctx = {"offer": ctx["offer"],
               "expected_objections": _texts(b.get("objections"), "objection")}
    else:
        raise ValueError(f"Unknown brain purpose: {purpose}")
    return _trim(ctx)


def _trim(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drop the longest lists' tail entries until the block fits MAX_CHARS."""
    while len(json.dumps(ctx, ensure_ascii=False)) > MAX_CHARS:
        lists = [(k, v) for k, v in ctx.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            break
        key, values = max(lists, key=lambda kv: len(kv[1]))
        ctx[key] = values[:-1]
    return ctx
