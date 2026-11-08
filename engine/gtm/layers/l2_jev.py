"""Layer 2 AI decisions with TypeSafe Jev 1.14 (OpenRouter Decisions API). Jev is the only AI
used for qualification, ICP scoring and classification; there is no fallback model.

Per account, one request with typed questions about company-level facts (never personal data):
  not_a_buyer  noul   associations, media, public bodies, IT firms, consultancies, staffing
  icp_fit      score  poor / possible / strong fit for an operations-automation offer
  title_N      noul   is job title N manual administrative work?
Answers are stored in jev_decisions; every request is logged in jev_calls (model ID reported by
the API, tokens, cost, latency). Then the accounts are re-scored from the crawl cache.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from gtm import budget, brain, db
from gtm.config import ClientConfig
from gtm.layers import l2_prefilter
from gtm.sources.jev import JevClient, JevResult, JevUnavailable, check_policy, scrub

VENDOR = "openrouter"

ICP = ("Buyer profile: Dutch or Belgian companies with 50-500 employees in logistics, wholesale and "
       "distribution, installation and technical services, or manufacturing, that run operations and "
       "finance processes (invoices, orders, planning) where manual admin work can be automated.")


@dataclass
class JevPlan:
    items: list[dict]
    est_cost: float
    model: str


def price_key(cfg: ClientConfig) -> str:
    return f"openrouter:{cfg.ai['model']}:request"


def plan(cfg: ClientConfig, conn, limit: int | None = None, redo: bool = False) -> JevPlan:
    check_policy(cfg.ai)
    done = "" if redo else " AND a.id NOT IN (SELECT account_id FROM jev_decisions)"
    rows = conn.execute(
        "SELECT a.id, a.name, a.industry, a.country, a.employee_range, s.home_title, s.home_excerpt,"
        " s.job_titles FROM accounts a JOIN l2_scores s ON s.account_id=a.id"
        f" WHERE a.client=? AND a.status IN ('tier_1','tier_2','tier_3'){done} ORDER BY a.id",
        (cfg.slug,)).fetchall()
    items = [dict(r) | {"job_titles": json.loads(r["job_titles"])} for r in rows]
    if limit:
        items = items[:limit]
    est = budget.estimate(cfg, price_key(cfg), len(items)) if items else 0.0
    return JevPlan(items, est, cfg.ai["model"])


def build_request(cfg: ClientConfig, item: dict) -> tuple[dict, dict, dict[str, str]]:
    titles = item["job_titles"][: cfg.ai.get("max_titles_per_request", 15)]
    state = {
        "company": item["name"],
        "linkedin_industry": item["industry"],
        "country": item["country"],
        "employees": item["employee_range"],
        "website_title": item["home_title"],
        "website_excerpt": (item["home_excerpt"] or "")[:1200],
        "open_job_titles": titles,
    }
    seller = brain.jev_context(cfg, "account")
    if seller:
        state["seller_context"] = seller
    questions = {
        "not_a_buyer": {
            "type": "noul",
            "instructions": ("Is this organisation clearly NOT a commercial company that could buy process "
                             "automation? Not a buyer: trade associations, unions, foundations, media and "
                             "magazines, schools and training bodies, government bodies and port authorities, "
                             "software or IT companies, consultancies, staffing agencies, and companies that "
                             "sell the same kind of service as the seller (see seller_context)."),
            "criteria": {"true": "Not a possible buyer (one of the listed types)",
                         "false": "A commercial operating company that could buy"},
        },
        "icp_fit": {
            "type": "score",
            "instructions": "How well does this company match the buyer profile? " + (cfg.icp.buyer_profile or ICP),
            "criteria": ["Poor fit", "Possible fit", "Strong fit"],
        },
    }
    title_keys: dict[str, str] = {}
    for n, title in enumerate(titles):
        key = f"title_{n}"
        title_keys[key] = title
        questions[key] = {
            "type": "noul",
            "instructions": (f'Is the job title "{title}" manual administrative work: invoices, accounts '
                             "payable or receivable, order entry or processing, data entry, back office, or "
                             "administrative planning support? Drivers, warehouse staff, engineers, technicians, "
                             "sales, IT, HR, controllers and managers are not."),
            "criteria": {"true": "Manual administrative work", "false": "Any other kind of role"},
        }
    return state, questions, title_keys


def _log_call(conn, cfg: ClientConfig, account_id: int, result: JevResult | None, error: str | None) -> None:
    conn.execute(
        "INSERT INTO jev_calls(client, account_id, requested_model, model_id, input_tokens, output_tokens,"
        " cost_usd, latency_ms, request_id, status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cfg.slug, account_id, cfg.ai["model"],
         result.model_id if result else None, result.input_tokens if result else None,
         result.output_tokens if result else None, result.cost_usd if result else None,
         result.latency_ms if result else None, result.request_id if result else None,
         "succeeded" if result else "failed", scrub(error)[:500] if error else None, db.now_iso()))


def _save_decision(conn, account_id: int, result: JevResult, title_keys: dict[str, str]) -> None:
    a = result.answers
    titles = {title: float(a[key]["noul"]) for key, title in title_keys.items()}
    conn.execute(
        "INSERT OR REPLACE INTO jev_decisions(account_id, model_id, not_a_buyer, icp_fit, icp_confidence,"
        " titles_json, raw_answers, decided_at) VALUES (?,?,?,?,?,?,?,?)",
        (account_id, result.model_id, float(a["not_a_buyer"]["noul"]), float(a["icp_fit"]["score"]),
         a["icp_fit"].get("confidence"), json.dumps(titles, ensure_ascii=False),
         json.dumps(a, ensure_ascii=False), db.now_iso()))


def run(cfg: ClientConfig, conn, jp: JevPlan, client: JevClient | None = None, workers: int | None = None) -> dict:
    """Decide every planned account. Stops at the first Jev failure (after logging it) and raises
    JevUnavailable: no retries with other models. Decisions already saved are kept and re-scored."""
    check_policy(cfg.ai)
    jev = client or JevClient(cfg.ai)
    budget.check(conn, cfg, VENDOR, jp.est_cost)
    totals = {"decided": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "models": set()}
    decided_ids: list[int] = []
    run_id = db.start_run(conn, cfg.slug, "L2-JEV", VENDOR, f"{jp.model} x{len(jp.items)}", jp.est_cost,
                          {"model": jp.model, "accounts": len(jp.items)})
    failure: Exception | None = None

    def ask(item):
        state, questions, keys = build_request(cfg, item)
        return item, keys, jev.decide(state, questions)

    with ThreadPoolExecutor(max_workers=workers or cfg.ai.get("workers", 4)) as pool:
        pending = [pool.submit(ask, item) for item in jp.items]
        for fut in as_completed(pending):
            try:
                item, keys, result = fut.result()
            except JevUnavailable as exc:
                _log_call(conn, cfg, None, None, str(exc))
                failure = failure or exc
                for other in pending:
                    other.cancel()
                continue
            _log_call(conn, cfg, item["id"], result, None)
            _save_decision(conn, item["id"], result, keys)
            conn.commit()
            decided_ids.append(item["id"])
            totals["decided"] += 1
            totals["cost_usd"] += result.cost_usd
            totals["input_tokens"] += result.input_tokens
            totals["output_tokens"] += result.output_tokens
            totals["models"].add(result.model_id)

    db.finish_run(conn, run_id, "failed" if failure else "succeeded", totals["decided"], totals["cost_usd"],
                  json.dumps({"models": sorted(totals["models"]), "input_tokens": totals["input_tokens"],
                              "output_tokens": totals["output_tokens"],
                              "error": scrub(str(failure)) if failure else None}))
    if decided_ids:
        totals["rescored"] = l2_prefilter.run(cfg, conn, account_ids=decided_ids)
    totals["models"] = sorted(totals["models"])
    if failure:
        raise JevUnavailable(f"{failure} ({totals['decided']} accounts were decided and saved before the stop.)")
    return totals


def purge_legacy_ai(conn, client: str) -> dict:
    """Remove verdicts made before the Jev 1.14 policy (Jev Router routed them to other models).
    Accounts go back to qualified_l1 so the next prefilter/jev run decides them again."""
    ev = conn.execute("DELETE FROM evidence WHERE layer='L2-AI' AND account_id IN"
                      " (SELECT id FROM accounts WHERE client=?)", (client,)).rowcount
    dropped = conn.execute("UPDATE accounts SET status='qualified_l1', status_reason=NULL"
                           " WHERE client=? AND status_reason LIKE 'ai:%'", (client,)).rowcount
    flagged = conn.execute("SELECT COUNT(*) FROM l2_scores s JOIN accounts a ON a.id=s.account_id"
                           " WHERE a.client=? AND s.flags LIKE '%reviewed:%'", (client,)).fetchone()[0]
    conn.commit()
    return {"evidence_removed": ev, "drops_undone": dropped, "accounts_with_old_flags": flagged}
