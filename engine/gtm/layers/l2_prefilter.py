"""Layer 2: cheap pre-filter. Crawl each Layer 1 account's website and careers page, find
evidence with rules, score fit and signals from scoring.yaml, and assign a tier. No paid calls:
the only cost is time. Accounts below Tier 3 are dropped before Layer 3 spends money on contacts.

Unclear accounts (vacancies found but no rule matched) are flagged for an AI review of their
job titles, done by Claude Code or Jev, instead of being guessed at here.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from gtm import db
from gtm.config import ClientConfig
from gtm.crawl import Fetcher, SiteCrawl, crawl_site
from gtm.layers.l1_discover import band_midpoint
from gtm.normalize import has_keyword, size_range
from gtm.signals import Evidence, extract, is_dutch


@dataclass
class Score:
    fit: int
    signal: int
    tier: str
    breakdown: dict
    flags: list[str] = field(default_factory=list)


def fit_score(cfg: ClientConfig, account: dict, site: SiteCrawl | None, evidence: list[Evidence]) -> tuple[int, dict]:
    rules = cfg.scoring["fit"]
    parts: dict[str, int] = {}

    start, end = size_range(account.get("employee_range"))
    mid = band_midpoint(start, end)
    if mid is None:
        mid = account.get("employee_count")
    if mid is not None:
        if cfg.icp.company.employees_min <= mid <= cfg.icp.company.employees_max:
            parts["employees"] = rules["employees"]["in_range"]
            s_lo, s_hi = rules["employees"]["sweet_spot"]
            if s_lo <= mid <= s_hi:
                parts["sweet_spot"] = rules["employees"]["sweet_spot_bonus"]

    groups = {s.name: s.industry_group for s in cfg.icp.segments}
    weights = [rules["industry_group"].get(groups.get(seg), 0) for seg in json.loads(account["segments"])]
    if weights:
        parts["industry"] = max(weights)

    parts["country"] = rules["country"].get(account.get("country") or "", 0)
    if site and site.home.ok:
        parts["website"] = rules["website_reachable"]
        if is_dutch(site):
            parts["dutch_site"] = rules["dutch_language_site"]
    if any(e.signal == "subsidiary_of_large_group" for e in evidence):
        parts["subsidiary"] = rules.get("subsidiary_of_large_group", 0)
    return max(0, sum(parts.values())), parts


def signal_score(cfg: ClientConfig, site: SiteCrawl | None, evidence: list[Evidence]) -> tuple[int, dict]:
    w = cfg.scoring["signals"]
    present = {e.signal for e in evidence}
    parts: dict[str, int] = {}
    admin_labels = {e.label for e in evidence if e.signal == "admin_job_ad"}
    if admin_labels:
        parts["admin_job_ad"] = w["admin_job_ad"]
    if len(admin_labels) >= 2:
        parts["multiple_admin_ads"] = w["multiple_admin_ads"]
    if "manual_process_language" in present:
        parts["manual_process_language"] = w["manual_process_language"]
    if "erp_mention" in present:
        parts["erp_mention"] = w["erp_mention"]
    if "headcount_growth" in present or (site and len(site.job_titles) >= 5):
        parts["headcount_growth"] = w["headcount_growth"]
    return min(100, sum(parts.values())), parts


def tier_for(cfg: ClientConfig, fit: int, signal: int) -> str:
    t = cfg.scoring["tiers"]
    if fit >= t["tier_1"]["fit_min"] and signal >= t["tier_1"]["signal_min"]:
        return "tier_1"
    fit_only = t.get("tier_2_fit_only", {}).get("fit_min")
    if (fit >= t["tier_2"]["fit_min"] and signal >= t["tier_2"]["signal_min"]) or (fit_only and fit >= fit_only):
        return "tier_2"
    if fit >= t["tier_3"]["fit_min"]:
        return "tier_3"
    return "rejected_l2"


def score_account(cfg: ClientConfig, account: dict, site: SiteCrawl | None) -> tuple[Score, list[Evidence]]:
    evidence = extract(site) if site else []
    fit, fit_parts = fit_score(cfg, account, site, evidence)
    signal, sig_parts = signal_score(cfg, site, evidence)
    flags = []
    if not account.get("website"):
        flags.append("no_website")
    elif site and not site.home.ok:
        flags.append(f"unreachable:{site.home.error or site.home.status}")
    if site and site.job_link_count and "admin_job_ad" not in sig_parts and fit >= 60:
        flags.append("review_job_titles")
    if any(e.signal == "subsidiary_of_large_group" for e in evidence):
        flags.append("subsidiary")
    return Score(fit, signal, tier_for(cfg, fit, signal), {"fit": fit_parts, "signals": sig_parts}, flags), evidence


def _save(conn, account_id: int, site: SiteCrawl | None, score: Score, evidence: list[Evidence]) -> None:
    ts = db.now_iso()
    conn.execute("DELETE FROM evidence WHERE account_id=? AND layer='L2'", (account_id,))
    for e in evidence:
        conn.execute(
            "INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
            (account_id, "L2", e.signal, e.label, e.url, e.quote, ts))
    conn.execute(
        "INSERT OR REPLACE INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, careers_url,"
        " job_link_count, job_titles, flags, breakdown, scored_at, home_title)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (account_id, score.fit, score.signal, score.tier,
         int(bool(site and site.home.ok)), int(bool(site and site.home.ok and is_dutch(site))),
         site.careers.url if site and site.careers and site.careers.ok else None,
         site.job_link_count if site else 0,
         json.dumps((site.job_titles if site else [])[:30], ensure_ascii=False),
         json.dumps(score.flags), json.dumps(score.breakdown), ts,
         (site.home.title[:200] if site and site.home.ok else None)))
    reason = None if score.tier != "rejected_l2" else f"fit {score.fit} below tier 3"
    conn.execute("UPDATE accounts SET status=?, status_reason=? WHERE id=?", (score.tier, reason, account_id))


def review_items(conn, client: str, include_all: bool = False) -> list[dict]:
    """Accounts for the AI review: by default those flagged review_job_titles; with include_all,
    every scored account (to also catch non-buyers such as associations or public bodies)."""
    where = "" if include_all else " AND s.flags LIKE '%review_job_titles%'"
    rows = conn.execute(
        "SELECT a.id, a.name, a.domain, a.industry, s.tier, s.home_title, s.careers_url, s.job_titles"
        " FROM accounts a JOIN l2_scores s ON s.account_id=a.id"
        f" WHERE a.client=? AND s.tier != 'rejected_l2'{where} ORDER BY a.id", (client,)).fetchall()
    return [{"account_id": r["id"], "name": r["name"], "domain": r["domain"], "industry": r["industry"],
             "tier": r["tier"], "home_title": r["home_title"], "careers_url": r["careers_url"],
             "job_titles": json.loads(r["job_titles"])} for r in rows]


def apply_review(cfg: ClientConfig, conn, reviews: list[dict], reviewer: str) -> dict:
    """Apply AI verdicts. Each review: {"account_id", "admin_roles": [job titles that are manual
    admin/order/invoice work], "not_a_buyer": bool, "reason": str}. Only titles that were in the
    export may be cited, so every new signal still points to a real job ad."""
    w = cfg.scoring["signals"]
    counts = {"reviewed": 0, "changed_tier": 0, "dropped": 0, "ignored_titles": 0}
    for rv in reviews:
        row = conn.execute(
            "SELECT s.* FROM l2_scores s JOIN accounts a ON a.id=s.account_id WHERE s.account_id=? AND a.client=?",
            (rv["account_id"], cfg.slug)).fetchone()
        if not row:
            continue
        counts["reviewed"] += 1
        flags = [f for f in json.loads(row["flags"]) if f != "review_job_titles"] + [f"reviewed:{reviewer}"]
        if rv.get("not_a_buyer"):
            reason = f"ai:not_a_buyer:{(rv.get('reason') or '')[:80]}"
            conn.execute("UPDATE l2_scores SET tier='rejected_l2', flags=? WHERE account_id=?",
                         (json.dumps(flags), row["account_id"]))
            conn.execute("UPDATE accounts SET status='rejected_l2', status_reason=? WHERE id=?",
                         (reason, row["account_id"]))
            counts["dropped"] += 1
            continue
        known = set(json.loads(row["job_titles"]))
        roles = [t for t in rv.get("admin_roles", []) if t in known]
        counts["ignored_titles"] += len(rv.get("admin_roles", [])) - len(roles)
        breakdown = json.loads(row["breakdown"])
        sig = breakdown.setdefault("signals", {})
        ts = db.now_iso()
        for role in roles:
            conn.execute(
                "INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
                (row["account_id"], "L2-AI", "admin_job_ad", f"job title ({reviewer})",
                 row["careers_url"] or "", role, ts))
        if roles:
            sig["admin_job_ad"] = w["admin_job_ad"]
        if len(roles) >= 2:
            sig["multiple_admin_ads"] = w["multiple_admin_ads"]
        signal = min(100, sum(sig.values()))
        tier = tier_for(cfg, row["fit"], signal)
        conn.execute("UPDATE l2_scores SET signal=?, tier=?, flags=?, breakdown=? WHERE account_id=?",
                     (signal, tier, json.dumps(flags), json.dumps(breakdown), row["account_id"]))
        conn.execute("UPDATE accounts SET status=? WHERE id=?", (tier, row["account_id"]))
        counts["changed_tier"] += tier != row["tier"]
    conn.commit()
    return counts


def run(cfg: ClientConfig, conn, limit: int | None = None, rescore: bool = False, workers: int = 8,
        fetcher_factory=Fetcher) -> dict:
    statuses = ("qualified_l1", "tier_1", "tier_2", "tier_3", "rejected_l2") if rescore else ("qualified_l1",)
    marks = ",".join("?" * len(statuses))
    sql = f"SELECT * FROM accounts WHERE client=? AND status IN ({marks}) ORDER BY id"
    accounts = [dict(r) for r in conn.execute(sql, (cfg.slug, *statuses)).fetchall()]
    # Exclusion keywords may have been added after Layer 1 ran: re-check names before crawling.
    kept = []
    for acc in accounts:
        kw = has_keyword(acc["name"], cfg.icp.exclusions.name_keywords)
        if kw:
            conn.execute("UPDATE accounts SET status='rejected_l1', status_reason=? WHERE id=?",
                         (f"excluded_keyword:{kw}", acc["id"]))
            conn.execute("DELETE FROM l2_scores WHERE account_id=?", (acc["id"],))
        else:
            kept.append(acc)
    conn.commit()
    accounts = kept[:limit] if limit else kept
    run_id = db.start_run(conn, cfg.slug, "L2", "crawl", f"{len(accounts)} accounts", 0.0, {"limit": limit})

    def work(acc):
        try:
            site = crawl_site(fetcher_factory(), acc["website"]) if acc.get("website") else None
        except Exception as exc:  # noqa: BLE001 - score the account without a site, flag it
            from gtm.crawl import Page
            site = SiteCrawl(home=Page(url=acc["website"], status=0, error=f"crawl_error:{type(exc).__name__}"))
        return acc, site

    summary = {"accounts": len(accounts), "tier_1": 0, "tier_2": 0, "tier_3": 0, "rejected_l2": 0,
               "unreachable": 0, "review_job_titles": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, a) for a in accounts]
        for fut in as_completed(futures):
            acc, site = fut.result()
            score, evidence = score_account(cfg, acc, site)
            _save(conn, acc["id"], site, score, evidence)
            conn.commit()
            summary[score.tier] += 1
            summary["unreachable"] += any(f.startswith("unreachable") for f in score.flags)
            summary["review_job_titles"] += "review_job_titles" in score.flags
    db.finish_run(conn, run_id, "succeeded", len(accounts), 0.0, json.dumps(summary))
    return summary
