"""Layer 2 AI decisions with TypeSafe Jev 1.14 (OpenRouter Decisions API). Jev is the only AI
used for qualification, ICP scoring and classification; there is no fallback model.

Per account, one request with typed questions about company-level facts (never personal data):
  not_a_buyer  noul   associations, media, public bodies, ... (ai.yaml `not_a_buyer`; default: The Marble Jar's)
  icp_fit      score  poor / possible / strong fit for the client's buyer profile (icp.yaml)
  title_N      noul   is job title N the kind of role the offer replaces? (ai.yaml `job_titles`;
                      default: manual administrative work)
  lookalike    score  how similar to the client's best customers (only when best_clients.csv is imported)
  evidence_N   noul   optional (ai.yaml `job_evidence`): is word match N on the careers page really an
                      open role? Stored per match in jev_decisions.checks_json
Answers are stored in jev_decisions; every request is logged in jev_calls (model ID reported by
the API, tokens, cost, latency). Then the accounts are re-scored from the crawl cache.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from gtm import best_clients, budget, brain, db
from gtm.config import ClientConfig
from gtm.layers import l2_prefilter
from gtm.sources.jev import JevClient, JevResult, JevUnavailable, check_policy, scrub

VENDOR = "openrouter"

ICP = ("Buyer profile: Dutch or Belgian companies with 50-500 employees in logistics, wholesale and "
       "distribution, installation and technical services, or manufacturing, that run operations and "
       "finance processes (invoices, orders, planning) where manual admin work can be automated.")

# Defaults (The Marble Jar). A client overrides them in ai.yaml: `not_a_buyer` and `job_titles`.
NOT_A_BUYER = {
    "instructions": ("Is this organisation clearly NOT a commercial company that could buy process "
                     "automation? Not a buyer: trade associations, unions, foundations, media and "
                     "magazines, schools and training bodies, government bodies and port authorities, "
                     "software or IT companies, consultancies, staffing agencies, and companies that "
                     "sell the same kind of service as the seller (see seller_context)."),
    "true": "Not a possible buyer (one of the listed types)",
    "false": "A commercial operating company that could buy",
}
JOB_TITLES = {
    "question": ('Is the job title "{title}" manual administrative work: invoices, accounts '
                 "payable or receivable, order entry or processing, data entry, back office, or "
                 "administrative planning support? Drivers, warehouse staff, engineers, technicians, "
                 "sales, IT, HR, controllers and managers are not."),
    "true": "Manual administrative work",
    "false": "Any other kind of role",
}


def _prompt(cfg: ClientConfig, key: str, default: dict) -> dict:
    return default | (cfg.ai.get(key) or {})


@dataclass
class JevPlan:
    items: list[dict]
    est_cost: float
    model: str
    best_clients: list[dict] = field(default_factory=list)


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
    if cfg.ai.get("job_evidence"):
        # Word matches for the job signal that Jev has to confirm (not the titles it already judges).
        cap = cfg.ai.get("max_evidence_per_request", 8)
        for item in items:
            ev = conn.execute(
                "SELECT label, quote FROM evidence WHERE account_id=? AND layer='L2' AND signal=?"
                " AND label NOT LIKE 'job title: %' ORDER BY id",
                (item["id"], l2_prefilter.job_signal(cfg))).fetchall()
            item["job_evidence"] = [dict(e) for e in ev][:cap]
    est = budget.estimate(cfg, price_key(cfg), len(items)) if items else 0.0
    return JevPlan(items, est, cfg.ai["model"], best_clients.jev_profiles(cfg, conn))


def build_request(cfg: ClientConfig, item: dict,
                  best: list[dict] | None = None) -> tuple[dict, dict, dict[str, str]]:
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
    nab, jt = _prompt(cfg, "not_a_buyer", NOT_A_BUYER), _prompt(cfg, "job_titles", JOB_TITLES)
    questions = {
        "not_a_buyer": {
            "type": "noul",
            "instructions": nab["instructions"],
            "criteria": {"true": nab["true"], "false": nab["false"]},
        },
        "icp_fit": {
            "type": "score",
            "instructions": "How well does this company match the buyer profile? " + (cfg.icp.buyer_profile or ICP),
            "criteria": ["Poor fit", "Possible fit", "Strong fit"],
        },
    }
    if best:
        state["sellers_best_customers"] = best
        questions["lookalike"] = {
            "type": "score",
            "instructions": ("How similar is this company to the seller's best customers "
                             "(sellers_best_customers): what it does, its size, and how it operates?"),
            "criteria": ["Not similar", "Somewhat similar", "Very similar"],
        }
    je = cfg.ai.get("job_evidence")
    for n, ev in enumerate(item.get("job_evidence") or [] if je else []):
        questions[f"evidence_{n}"] = {
            "type": "noul",
            "instructions": je["question"].replace("{label}", ev["label"]).replace("{quote}", ev["quote"]),
            "criteria": {"true": je["true"], "false": je["false"]},
        }
    title_keys: dict[str, str] = {}
    for n, title in enumerate(titles):
        key = f"title_{n}"
        title_keys[key] = title
        questions[key] = {
            "type": "noul",
            "instructions": jt["question"].replace("{title}", title),
            "criteria": {"true": jt["true"], "false": jt["false"]},
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


def _save_decision(conn, account_id: int, result: JevResult, title_keys: dict[str, str],
                   job_evidence: list[dict] | None = None) -> None:
    a = result.answers
    titles = {title: float(a[key]["noul"]) for key, title in title_keys.items()}
    # Checks of word matches are kept across decisions: a match Jev rejected stays rejected until the
    # page text around it changes (then it is a new match with a new key).
    old = conn.execute("SELECT checks_json FROM jev_decisions WHERE account_id=?", (account_id,)).fetchone()
    checks = json.loads(old["checks_json"] or "{}") if old else {}
    for n, ev in enumerate(job_evidence or []):
        if f"evidence_{n}" in a:
            checks[l2_prefilter.evidence_key(ev["label"], ev["quote"])] = float(a[f"evidence_{n}"]["noul"])
    conn.execute(
        "INSERT OR REPLACE INTO jev_decisions(account_id, model_id, not_a_buyer, icp_fit, icp_confidence,"
        " titles_json, raw_answers, decided_at, lookalike, checks_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (account_id, result.model_id, float(a["not_a_buyer"]["noul"]), float(a["icp_fit"]["score"]),
         a["icp_fit"].get("confidence"), json.dumps(titles, ensure_ascii=False),
         json.dumps(a, ensure_ascii=False), db.now_iso(),
         float(a["lookalike"]["score"]) if "lookalike" in a else None,
         json.dumps(checks, ensure_ascii=False)))


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
        state, questions, keys = build_request(cfg, item, jp.best_clients)
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
            _save_decision(conn, item["id"], result, keys, item.get("job_evidence"))
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
