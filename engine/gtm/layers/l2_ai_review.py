"""Layer 2 AI review through OpenRouter (default: TypeSafe's Jev Router).

The rules in gtm/signals.py cannot read every job title, and cannot tell an association or a
public body from a real buyer. This step sends company-level facts only (name, website title,
industry, job titles; never personal data) in small batches, asks for strict JSON, checks every
answer against what we crawled, and applies it with l2_prefilter.apply_review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from gtm import budget, db
from gtm.config import ClientConfig
from gtm.layers import l2_prefilter
from gtm.sources.openrouter import DEFAULT_MODEL, OpenRouterClient

VENDOR = "openrouter"

SYSTEM = """You review B2B companies for an outbound campaign selling process automation
(automating invoice handling, order entry, data entry and other manual admin work) to Dutch and
Belgian operations-heavy companies.

For each company you get its name, industry, website title and the job titles found on its
careers page. Decide two things:

1. admin_roles: copy, character for character, only those job titles that are manual
   administrative work: invoices, accounts payable or receivable, order entry or processing,
   data entry, back office, administrative planning support. Do not include drivers, warehouse
   staff, engineers, technicians, sales, IT, HR, finance controllers or managers. Use [] if none.
2. not_a_buyer: true only if the company is clearly not a commercial company that could buy this:
   trade associations, unions, foundations, media and magazines, schools and training bodies,
   government and port authorities, software or IT companies, consultancies, staffing agencies.
   Give a short reason in English when true; otherwise reason is "".

Return one review per company, using its account_id. Never invent titles."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "integer"},
                    "admin_roles": {"type": "array", "items": {"type": "string"}},
                    "not_a_buyer": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["account_id", "admin_roles", "not_a_buyer", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}


@dataclass
class ReviewPlan:
    items: list[dict]
    batches: list[list[dict]]
    model: str
    est_cost: float


def plan(cfg: ClientConfig, conn, include_all: bool, batch_size: int, limit: int | None,
         model: str = DEFAULT_MODEL) -> ReviewPlan:
    items = [i for i in l2_prefilter.review_items(conn, cfg.slug, include_all=include_all)
             if "reviewed:" not in (conn.execute("SELECT flags FROM l2_scores WHERE account_id=?",
                                                 (i["account_id"],)).fetchone()[0] or "")]
    if limit:
        items = items[:limit]
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    est = budget.estimate(cfg, f"openrouter:{model}:batch", len(batches)) if batches else 0.0
    return ReviewPlan(items, batches, model, est)


def _prompt(batch: list[dict]) -> str:
    slim = [{"account_id": i["account_id"], "name": i["name"], "industry": i["industry"],
             "website_title": i["home_title"], "job_titles": i["job_titles"][:25]} for i in batch]
    return "Companies:\n" + json.dumps(slim, ensure_ascii=False, indent=1)


def validate(batch: list[dict], data: dict) -> list[dict]:
    """Keep only reviews for accounts in this batch, and only titles that were in the batch."""
    by_id = {i["account_id"]: i for i in batch}
    clean = []
    for rv in data.get("reviews", []):
        item = by_id.get(rv.get("account_id"))
        if not item:
            continue
        titles = set(item["job_titles"])
        clean.append({
            "account_id": item["account_id"],
            "admin_roles": [t for t in rv.get("admin_roles", []) if t in titles],
            "not_a_buyer": bool(rv.get("not_a_buyer")),
            "reason": str(rv.get("reason", ""))[:120],
        })
    return clean


def run(cfg: ClientConfig, conn, rp: ReviewPlan, client: OpenRouterClient | None = None) -> dict:
    totals = {"batches": 0, "reviewed": 0, "changed_tier": 0, "dropped": 0, "ignored_titles": 0,
              "cost_usd": 0.0, "models": set()}
    unit = cfg.limits.unit_price_usd.get(f"openrouter:{rp.model}:batch", 0.0)
    for batch in rp.batches:
        budget.check(conn, cfg, VENDOR, unit)
        run_id = db.start_run(conn, cfg.slug, "L2-AI", VENDOR, f"{rp.model} x{len(batch)}", unit,
                              {"model": rp.model, "accounts": [i["account_id"] for i in batch]})
        try:
            decision = (client or OpenRouterClient()).decide(
                rp.model, SYSTEM, _prompt(batch), "company_reviews", SCHEMA)
        except Exception as exc:
            db.finish_run(conn, run_id, "failed", 0, None, str(exc)[:500])
            raise
        reviews = validate(batch, decision.data)
        counts = l2_prefilter.apply_review(cfg, conn, reviews, reviewer=f"ai:{rp.model}")
        db.finish_run(conn, run_id, "succeeded", len(reviews), decision.cost_usd,
                      f"model_used={decision.model_used}")
        totals["batches"] += 1
        totals["cost_usd"] += decision.cost_usd
        totals["models"].add(decision.model_used)
        for key in ("reviewed", "changed_tier", "dropped", "ignored_titles"):
            totals[key] += counts[key]
    totals["models"] = sorted(totals["models"])
    return totals
