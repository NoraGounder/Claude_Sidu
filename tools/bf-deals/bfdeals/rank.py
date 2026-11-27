"""Stage 4: shortlist offers deterministically, then ask Jev Router to pick.

The maths (landed cost, savings) is done in code. The model only judges:
which model is worth it, which deal is real, which caveat matters. Its
answer must cite offer ids from the shortlist; anything else is dropped.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.request
from collections import defaultdict

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


DIGITAL = {"llm", "software", "membership"}  # free trials sort last here; toolkit keeps free items


def shortlist(offers: list[dict], per_item: int = 3, max_items: int = 14) -> dict:
    """Best eligible offers per item, with a home-market reference price."""
    groups: dict[tuple, list] = defaultdict(list)
    for o in offers:
        if o.get("landed") is not None:
            groups[(o["category"], o["item"])].append(o)

    cats: dict[str, list] = defaultdict(list)
    for (cat, item), group in groups.items():
        # Free trials and cashback-only posts go last: they are hooks, not prices.
        ok = sorted((o for o in group if not o["blockers"]),
                    key=lambda o: (cat in DIGITAL and not o.get("price"), o["landed"]))
        blocked = [o for o in group if o["blockers"]]
        home_ref = [o["landed"] for o in group if o["market"] == "PL"]
        ref = min(home_ref) if home_ref else None
        entry = {
            "item": item,
            "home_ref_pln": ref,
            "median_pln": round(statistics.median(o["landed"] for o in group), 2),
            "offers": ok[: per_item + (2 if cat in DIGITAL else 0)],
            "blocked": sorted(blocked, key=lambda o: o["landed"])[:2],
        }
        if ok:
            top = ok[0]
            entry["best_pln"] = top["landed"]
            if ref:
                entry["saving_vs_ref_pct"] = round(100 * (1 - top["landed"] / ref), 1)
            elif top.get("list_price") and top.get("price"):
                entry["saving_vs_list_pct"] = round(100 * (1 - top["price"] / top["list_price"]), 1)
        cats[cat].append(entry)

    for cat, items in cats.items():
        if cat == "books":  # biggest absolute discounts and cheapest wins first
            items.sort(key=lambda e: (e.get("best_pln") or 1e9))
        else:
            items.sort(key=lambda e: -((e.get("saving_vs_ref_pct") or e.get("saving_vs_list_pct") or 0)
                                       + 3 * len(e["offers"])))
        cats[cat] = items[: {"books": 40, "vacuum": 22}.get(cat, max_items)]
    return dict(cats)


def _compact(o: dict) -> dict:
    keep = ("id", "retailer", "market", "currency", "price", "list_price", "voucher",
            "landed", "warnings", "posted_at", "votes", "format", "term", "age_guide", "note")
    d = {k: o[k] for k in keep if o.get(k) not in (None, [], "")}
    d["title"] = o["title"][:110]
    return d


def build_payload(short: dict, cfg: dict, fx: dict, lineup_rows: list | None = None) -> dict:
    lineup_rows = lineup_rows or []
    cats = {}
    for cat, items in short.items():
        cats[cat] = [{
            "item": e["item"], "home_ref_pln": e["home_ref_pln"], "best_pln": e.get("best_pln"),
            "saving_vs_ref_pct": e.get("saving_vs_ref_pct"), "saving_vs_list_pct": e.get("saving_vs_list_pct"),
            "offers": [_compact(o) for o in e["offers"]],
            "blocked_examples": [{"id": o["id"], "market": o["market"], "landed": o["landed"],
                                  "why": o["blockers"]} for o in e["blocked"]],
        } for e in items]
    return {
        "home_country": cfg["home_country"], "currency": cfg["report_currency"],
        "fx": {"source": f"NBP table {fx['table']} ({fx['date']})",
               **{k: fx["rates"][k] for k in ("EUR", "GBP", "USD")}},
        "budget": cfg.get("budget", {}), "recipient_age": cfg.get("recipient_age", {}),
        "gift_delivery": cfg.get("gift_delivery", {}),
        "categories": cats,
        "buyer_context": cfg.get("buyer_context", ""),
        "vacuum_lineup": [{
            "item": r["item"], "score": r["score"], "tested": r.get("tested"), "rtings": r.get("rtings"),
            "spec_confidence": r["confidence"], "spec": r["spec"],
            "best_offer_id": r["best"]["id"] if r["best"] else None,
            "best_where": f"{r['best']['retailer']} ({r['best']['market']})" if r["best"] else None,
            "best_price": f"{r['best']['price']} {r['best']['currency']}" if r["best"] else None,
            "voucher": r["best"].get("voucher") if r["best"] else None,
            "best_warnings": r["best"]["warnings"] if r["best"] else [],
            "landed_pln": r["landed"], "pl_now_pln": r["pl_now"], "pl_30d_low_pln": r["pl_30d_low"],
            "vs_pl_pct": r["vs_pl_pct"], "value_pts_per_1000pln": r["value"], "tier": r["tier"],
            "frontier": r.get("frontier", False), "tier_winner": r.get("tier_winner", False),
        } for r in lineup_rows if r["landed"]],
    }


SYSTEM = """You are a sharp, frugal deal analyst. A buyer in Poland is shopping Black Friday \
across Poland, the EU, the UK and the US. All costs are already converted to landed PLN \
(VAT, customs, forwarding included) - trust the 'landed' numbers, never recompute them.

Rules:
- Pick only from the offer ids given. Never invent ids, prices or shops.
- A deal is only good if it beats the home reference (home_ref_pln) or the item's normal price.
- No debt, BNPL or instalment plans. Respect each category budget.
- Physical electronics need EU warranty and 230 V: prefer PL/EU offers.
- Gifts must suit the recipient's age; flag anything too young or too mature.
- Subscriptions: compare cost per year; say when there is no real Black Friday discount and \
the right move is to wait or to pay annually.
- Be blunt and short. Give the strongest reason against your own pick in 'watch_out'.

Robot vacuum: use vacuum_lineup. 'score' is the RTINGS lab score x 10 where 'tested' is true; \
for untested models it is an estimate from a spec rubric - never prefer an untested model over a \
tested one on the estimate alone. 'value_pts_per_1000pln' = score per 1,000 zł landed. \
Landed prices for German shops include a parcel forwarder; Polish offers are cash prices. \
Choose a 'deal_of_the_century': the tested model (score >= 75) with the best value at a cash \
price. 'vs_pl_pct' is only a tiebreak: an import saving is not product quality, and when a \
Polish cash price is within about 5% of an import, prefer Polish (local returns and warranty). \
Also pick the best model per tier. If previous_deal_of_the_century is given and its landed \
price has not risen, keep it unless another model's numbers clearly beat it; say what moved.

Toolkit: the buyer is learning small-business acquisition (see buyer_context). Pick the few \
items worth paying for now and list the free ones worth joining; say what to skip.

Return ONLY a JSON object (ids must be offer ids from categories or best_offer_id):
{
 "vacuum":     {"deal_of_the_century": id, "pick": id, "runner_up": id,
                "tier_picks": {"entry": id, "mid": id, "premium": id}, "why": str, "watch_out": str},
 "comics":     {"picks": [id, id], "why": str, "watch_out": str},
 "books":      {"buy_now": [ids], "why": str, "watch_out": str},
 "llm":        {"pick": id|null, "why": str, "watch_out": str},
 "software":   {"picks": [ids], "why": str, "watch_out": str},
 "membership": {"picks": [ids], "why": str, "watch_out": str},
 "toolkit":    {"picks": [ids], "free": [ids], "why": str, "watch_out": str},
 "summary": str,
 "total_spend_pln": number
}"""


def ask_jev(payload: dict, cfg: dict) -> dict:
    llm = cfg.get("llm", {})
    body = {
        "model": llm.get("model", "typesafe/jev-router"),
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": llm.get("max_tokens", 16000),
        # Reasoning tokens count against max_tokens; a capped effort leaves room for the answer.
        "reasoning": {"effort": llm.get("reasoning_effort", "low")},
        "temperature": 0.2,
        "usage": {"include": True},
    }
    headers = {"Content-Type": "application/json", "X-Title": "bf-deals"}
    if os.environ.get("OPENROUTER_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['OPENROUTER_API_KEY']}"
    last_err = None
    for attempt in range(2):  # the router can land on a model that returns no content; retry once
        req = urllib.request.Request(OPENROUTER_URL, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.load(r)
        choice = resp["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if not text:
            last_err = f"empty content from {resp.get('model')} (finish_reason={choice.get('finish_reason')})"
            print(f"attempt {attempt + 1}: {last_err}")
            continue
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            return {"verdict": json.loads(text), "model": resp.get("model"), "usage": resp.get("usage", {})}
        except json.JSONDecodeError as e:
            last_err = f"invalid JSON from {resp.get('model')}: {e}"
            print(f"attempt {attempt + 1}: {last_err}")
    raise RuntimeError(last_err)


def validate(verdict: dict, offers_by_id: dict) -> tuple[dict, list[str]]:
    """Drop any id the model made up; report what was dropped."""
    problems = []

    def keep(x):
        if x is None or x in offers_by_id:
            return x
        problems.append(f"unknown offer id from model: {x}")
        return None

    for cat, v in verdict.items():
        if not isinstance(v, dict):
            continue
        for key in ("pick", "runner_up", "deal_of_the_century"):
            if key in v:
                v[key] = keep(v[key])
        if isinstance(v.get("tier_picks"), dict):
            v["tier_picks"] = {t: keep(i) for t, i in v["tier_picks"].items()}
        for key in ("picks", "buy_now", "free"):
            if key in v:
                v[key] = [i for i in (v[key] or []) if keep(i)]
    return verdict, problems


def fallback_verdict(short: dict, deal_row: dict | None = None) -> dict:
    """Cheapest eligible offer per category, used when the model is unavailable."""
    out = {}
    for cat, items in short.items():
        ids = [e["offers"][0]["id"] for e in items if e["offers"]]
        out[cat] = {"picks": ids[:3], "why": "Cheapest landed offers (no model verdict).", "watch_out": ""}
    if deal_row and deal_row.get("best"):
        out.setdefault("vacuum", {})["deal_of_the_century"] = deal_row["best"]["id"]
    out["summary"] = "Model verdict unavailable; showing cheapest landed offers."
    return out
