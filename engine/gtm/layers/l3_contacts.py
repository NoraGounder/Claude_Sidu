"""Layer 3: find decision-makers and their work emails, paying as little as possible.

Per Tier 1-3 account (cheapest first, nothing paid twice):
 1. FullEnrich people search: company domain + our persona titles, at most `search_limit` people
    (0.25 credit per person returned).
 2. Python rules: drop junior titles, owner-director titles at companies over the owner-led size,
    and anything suppressed.
 3. TypeSafe Jev 1.14 rates each remaining job title for buying relevance. Only titles are sent,
    never names. Jev failure stops the run; no other model is used.
 4. Keep the best `max_contacts` per tier (scoring.yaml enrichment_policy).
 5. FullEnrich work-email enrichment for the kept contacts only, in batches of up to 100
    (1 credit per email found, nothing when not found).
Every contact stores its data source (GDPR Art. 14). Contacts live only in data/ (gitignored).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from gtm import budget, db
from gtm.config import ClientConfig
from gtm.normalize import has_keyword, pick
from gtm.sources.fullenrich import FullEnrichClient
from gtm.sources.jev import JevClient, JevResult, JevUnavailable, check_policy, scrub

VENDOR = "fullenrich"
SEARCH_KEY = "fullenrich:person_returned"
EMAIL_KEY = "fullenrich:work_email"
OWNER_LED_MAX_EMPLOYEES = 150
ACCEPT_EMAIL = {"DELIVERABLE", "HIGH_PROBABILITY", "VALID"}
CATCH_ALL = {"CATCH_ALL", "ACCEPT_ALL", "RISKY"}


@dataclass
class ContactPlan:
    accounts: list[dict]
    search_limit: int
    est_search_cost: float


def policy(cfg: ClientConfig, tier: str) -> dict:
    return cfg.scoring.get("enrichment_policy", {}).get(tier, {"max_contacts": 1})


def _title_match(needle: str, title: str) -> bool:
    """Whole-word match, so 'COO' does not match 'Coordinator' and 'CEO' needs the word itself."""
    return re.search(r"(?<![\w-])" + re.escape(needle.lower()) + r"(?![\w-])", title.lower()) is not None


def persona_of(cfg: ClientConfig, title: str) -> str | None:
    for persona, titles in cfg.icp.personas.items():
        if persona == "exclude_titles":
            continue
        if any(_title_match(t, title or "") for t in titles):
            return persona
    return None


def plan(cfg: ClientConfig, conn, limit: int | None = None, search_limit: int = 4) -> ContactPlan:
    rows = conn.execute(
        "SELECT a.*, s.tier, s.fit, s.signal FROM accounts a JOIN l2_scores s ON s.account_id=a.id"
        " WHERE a.client=? AND a.status IN ('tier_1','tier_2','tier_3') AND a.domain IS NOT NULL"
        " AND a.id NOT IN (SELECT account_id FROM l3_progress)"
        " ORDER BY CASE s.tier WHEN 'tier_1' THEN 1 WHEN 'tier_2' THEN 2 ELSE 3 END, s.signal DESC, s.fit DESC",
        (cfg.slug,)).fetchall()
    suppressed = db.suppressed_values(conn, cfg.slug, "domain")
    accounts = [dict(r) for r in rows if r["domain"] not in suppressed]
    if limit:
        accounts = accounts[:limit]
    est = budget.estimate(cfg, SEARCH_KEY, len(accounts) * search_limit) if accounts else 0.0
    return ContactPlan(accounts, search_limit, est)


def _person_fields(p: dict) -> dict:
    return {
        "person_id": str(pick(p, "id") or ""),
        "full_name": pick(p, "full_name"),
        "first_name": pick(p, "first_name"),
        "last_name": pick(p, "last_name"),
        "title": pick(p, "employment.current.title", "headline"),
        "linkedin_url": pick(p, "social_profiles.professional_network.url"),
        "country": pick(p, "location.country_code", "location.country"),
    }


def screen(cfg: ClientConfig, account: dict, people: list[dict]) -> list[dict]:
    """Deterministic checks: right persona, not junior, owner titles only at owner-led sizes."""
    kept, seen = [], set()
    excluded = cfg.icp.personas.get("exclude_titles", [])
    size_mid = None
    nums = [int(n) for n in re.findall(r"\d+", account.get("employee_range") or "")]
    if nums:
        size_mid = sum(nums[:2]) / len(nums[:2])
    for raw in people:
        p = _person_fields(raw)
        if not p["title"] or not (p["first_name"] and p["last_name"]):
            continue
        if p["person_id"] in seen or has_keyword(p["title"], excluded):
            continue
        persona = persona_of(cfg, p["title"])
        if persona is None:
            continue
        if persona == "owner_led" and size_mid and size_mid > OWNER_LED_MAX_EMPLOYEES:
            continue
        seen.add(p["person_id"])
        kept.append(p | {"persona": persona})
    return kept


def relevance_request(account: dict, candidates: list[dict], offer: str = "") -> tuple[dict, dict]:
    """Jev request with job titles only (no names: data minimisation)."""
    state = {"company": account["name"], "industry": account.get("industry"),
             "employees": account.get("employee_range"),
             "offer": offer or "Automating manual operations and finance admin (invoices, orders, data entry)"}
    questions = {}
    for n, c in enumerate(candidates):
        questions[f"c{n}"] = {
            "type": "noul",
            "instructions": (f'Would a person with the job title "{c["title"]}" at this company decide on, or '
                             "strongly influence, buying automation of operations and finance admin processes?"),
            "criteria": {"true": "Decision-maker or strong influencer", "false": "Not involved in such a decision"},
        }
    return state, questions


def _log_jev(conn, cfg, account_id, result: JevResult | None, error: str | None) -> None:
    conn.execute(
        "INSERT INTO jev_calls(client, account_id, requested_model, model_id, input_tokens, output_tokens,"
        " cost_usd, latency_ms, request_id, status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cfg.slug, account_id, cfg.ai["model"], result.model_id if result else None,
         result.input_tokens if result else None, result.output_tokens if result else None,
         result.cost_usd if result else None, result.latency_ms if result else None,
         result.request_id if result else None, "succeeded" if result else "failed",
         scrub(error)[:500] if error else None, db.now_iso()))


def _store(conn, cfg, account_id: int, c: dict, status: str, rank: int | None, reason: str | None = None) -> int:
    ts = db.now_iso()
    conn.execute(
        "INSERT INTO contacts(client, account_id, person_id, full_name, first_name, last_name, title, linkedin_url,"
        " country, persona, jev_relevance, rank, status, status_reason, data_source, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(client, account_id, person_id) DO UPDATE SET"
        " status=excluded.status, rank=excluded.rank, jev_relevance=excluded.jev_relevance, updated_at=excluded.updated_at",
        (cfg.slug, account_id, c["person_id"], c["full_name"], c["first_name"], c["last_name"], c["title"],
         c["linkedin_url"], c["country"], c["persona"], c.get("jev_relevance"), rank, status, reason,
         f"FullEnrich people search, {ts[:10]}", ts, ts))
    return conn.execute("SELECT id FROM contacts WHERE client=? AND account_id=? AND person_id=?",
                        (cfg.slug, account_id, c["person_id"])).fetchone()[0]


def find_people(cfg: ClientConfig, conn, cp: ContactPlan, fe: FullEnrichClient | None = None,
                jev: JevClient | None = None) -> dict:
    """Steps 1-4. Stops on a Jev failure (no fallback); people already found are kept."""
    check_policy(cfg.ai)
    fe = fe or FullEnrichClient()
    jev = jev or JevClient(cfg.ai)
    budget.check(conn, cfg, VENDOR, cp.est_search_cost)
    titles = [t for p, ts in cfg.icp.personas.items() if p != "exclude_titles" for t in ts]
    credit_usd = cfg.limits.unit_price_usd["fullenrich:credit"]
    totals = {"accounts": 0, "people_returned": 0, "candidates": 0, "selected": 0, "credits": 0.0}
    run_id = db.start_run(conn, cfg.slug, "L3-search", VENDOR, f"people search x{len(cp.accounts)}",
                          cp.est_search_cost, {"accounts": len(cp.accounts), "limit": cp.search_limit})
    outcome = "failed"
    try:
        for acc in cp.accounts:
            res = fe.search_people(acc["domain"], titles, limit=cp.search_limit)
            totals["accounts"] += 1
            totals["people_returned"] += len(res.people)
            totals["credits"] += res.credits
            candidates = screen(cfg, acc, res.people)
            totals["candidates"] += len(candidates)
            conn.execute("INSERT OR REPLACE INTO l3_progress(account_id, searched_at, found, credits)"
                         " VALUES (?,?,?,?)", (acc["id"], db.now_iso(), len(candidates), res.credits))
            if candidates:
                state, questions = relevance_request(acc, candidates, cfg.icp.offer_summary)
                try:
                    result = jev.decide(state, questions)
                except JevUnavailable as exc:
                    _log_jev(conn, cfg, acc["id"], None, str(exc))
                    conn.commit()
                    raise
                _log_jev(conn, cfg, acc["id"], result, None)
                for n, c in enumerate(candidates):
                    c["jev_relevance"] = float(result.answers[f"c{n}"]["noul"])
                candidates.sort(key=lambda c: c["jev_relevance"], reverse=True)
                keep = policy(cfg, acc["tier"]).get("max_contacts", 1)
                for rank, c in enumerate(candidates, start=1):
                    chosen = rank <= keep and c["jev_relevance"] >= 0.5
                    _store(conn, cfg, acc["id"], c, "selected" if chosen else "candidate", rank,
                           None if chosen else "lower relevance or over the tier's contact limit")
                    totals["selected"] += chosen
            conn.commit()
        outcome = "succeeded"
    finally:
        db.finish_run(conn, run_id, outcome, totals["people_returned"], round(totals["credits"] * credit_usd, 4),
                      json.dumps(totals))
    totals["cost_usd"] = round(totals["credits"] * credit_usd, 4)
    return totals


def find_emails(cfg: ClientConfig, conn, fe: FullEnrichClient | None = None, limit: int | None = None) -> dict:
    """Step 5: work emails for selected contacts only, in batches of up to 100."""
    rows = conn.execute(
        "SELECT c.*, a.domain, a.name AS company FROM contacts c JOIN accounts a ON a.id=c.account_id"
        " WHERE c.client=? AND c.status='selected' ORDER BY c.id", (cfg.slug,)).fetchall()
    rows = [dict(r) for r in rows][: limit or None]
    totals = {"requested": len(rows), "found": 0, "catch_all": 0, "not_found": 0, "credits": 0.0}
    if not rows:
        return totals | {"cost_usd": 0.0}
    budget.check(conn, cfg, VENDOR, budget.estimate(cfg, EMAIL_KEY, len(rows)))
    fe = fe or FullEnrichClient()
    credit_usd = cfg.limits.unit_price_usd["fullenrich:credit"]
    for start in range(0, len(rows), 100):
        batch = rows[start:start + 100]
        est = budget.estimate(cfg, EMAIL_KEY, len(batch))
        run_id = db.start_run(conn, cfg.slug, "L3-email", VENDOR, f"work email x{len(batch)}", est,
                              {"contacts": [r["id"] for r in batch]})
        payload = [{"first_name": r["first_name"], "last_name": r["last_name"], "domain": r["domain"],
                    "company_name": r["company"], "linkedin_url": r["linkedin_url"],
                    "enrich_fields": ["contact.work_emails"], "custom": {"contact_id": str(r["id"])}}
                   for r in batch]
        try:
            enrichment_id = fe.start_enrichment(f"{cfg.slug} L3 {db.now_iso()[:16]}", payload)
            result = fe.wait_enrichment(enrichment_id)
        except Exception as exc:
            db.finish_run(conn, run_id, "failed", 0, None, scrub(str(exc))[:500])
            raise
        credits = float((result.get("cost") or {}).get("credits") or 0)
        totals["credits"] += credits
        for item in result.get("data", []):
            cid = int((item.get("custom") or {}).get("contact_id", 0))
            best = (item.get("contact_info") or {}).get("most_probable_work_email") or {}
            email, status = best.get("email"), (best.get("status") or "").upper()
            if email and status in ACCEPT_EMAIL:
                new_status, key = "email_found", "found"
            elif email and status in CATCH_ALL:
                new_status, key = "email_found", "catch_all"
            else:
                new_status, key, email = "no_email", "not_found", None
            totals[key] += 1
            ts = db.now_iso()
            conn.execute("UPDATE contacts SET status=?, email=?, email_status=?, email_source=?, updated_at=?,"
                         " verified_at=? WHERE id=? AND client=?",
                         (new_status, email, status or None, "FullEnrich" if email else None,
                          ts, ts if email else None, cid, cfg.slug))
        conn.commit()
        db.finish_run(conn, run_id, "succeeded", len(batch), round(credits * credit_usd, 4), enrichment_id)
    totals["cost_usd"] = round(totals["credits"] * credit_usd, 4)
    return totals
