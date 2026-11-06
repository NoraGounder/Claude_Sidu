"""Layer 2: cheap pre-filter. Crawl each Layer 1 account's website and careers page, find
evidence with rules, score fit and signals from scoring.yaml, and assign a tier. Crawling, rules
and arithmetic are deterministic Python. AI decisions come only from TypeSafe Jev 1.14
(gtm/layers/l2_jev.py); they are stored in jev_decisions and folded into every score here, so a
re-crawl or re-score never loses them.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from gtm import db
from gtm.config import ClientConfig
from gtm.crawl import Page, SiteCrawl, crawl_site, default_fetcher
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
    reason: str | None = None


def load_jev(conn, account_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jev_decisions WHERE account_id=?", (account_id,)).fetchone()
    if not row:
        return None
    return {"model_id": row["model_id"], "not_a_buyer": row["not_a_buyer"], "icp_fit": row["icp_fit"],
            "icp_confidence": row["icp_confidence"], "titles": json.loads(row["titles_json"])}


def jev_evidence(cfg: ClientConfig, site: SiteCrawl | None, jev: dict | None) -> list[Evidence]:
    if not jev:
        return []
    threshold = cfg.ai["thresholds"]["admin_role"]
    url = (site.careers.url if site and site.careers and site.careers.ok else
           site.home.url if site else "")
    return [Evidence("admin_job_ad", f"job title: {title}", url, f"{title} (Jev 1.14, p={p:.2f})")
            for title, p in jev["titles"].items() if p >= threshold]


def fit_score(cfg: ClientConfig, account: dict, site: SiteCrawl | None, evidence: list[Evidence],
              jev: dict | None = None) -> tuple[int, dict]:
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
    if jev and jev.get("icp_fit") is not None and rules.get("jev_icp_fit"):
        # Jev's ICP score is 0 (poor) .. 2 (strong); scale to the configured weight.
        parts["jev_icp_fit"] = round(rules["jev_icp_fit"] * jev["icp_fit"] / 2)
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


def score_account(cfg: ClientConfig, account: dict, site: SiteCrawl | None,
                  jev: dict | None = None) -> tuple[Score, list[Evidence]]:
    evidence = (extract(site) if site else []) + jev_evidence(cfg, site, jev)
    fit, fit_parts = fit_score(cfg, account, site, evidence, jev)
    signal, sig_parts = signal_score(cfg, site, evidence)
    flags = []
    if not account.get("website"):
        flags.append("no_website")
    elif site and not site.home.ok:
        flags.append(f"unreachable:{site.home.error or site.home.status}")
    if any(e.signal == "subsidiary_of_large_group" for e in evidence):
        flags.append("subsidiary")
    tier, reason = tier_for(cfg, fit, signal), None
    if tier == "rejected_l2":
        reason = f"fit {fit} below tier 3"
    if jev:
        flags.append("jev:" + jev["model_id"])
        if jev["not_a_buyer"] is not None and jev["not_a_buyer"] >= cfg.ai["thresholds"]["not_a_buyer"]:
            tier, reason = "rejected_l2", f"jev:not_a_buyer p={jev['not_a_buyer']:.2f}"
    return Score(fit, signal, tier, {"fit": fit_parts, "signals": sig_parts}, flags, reason), evidence


def _save(conn, account_id: int, site: SiteCrawl | None, score: Score, evidence: list[Evidence]) -> None:
    ts = db.now_iso()
    conn.execute("DELETE FROM evidence WHERE account_id=? AND layer='L2'", (account_id,))
    for e in evidence:
        conn.execute(
            "INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
            (account_id, "L2", e.signal, e.label, e.url, e.quote, ts))
    home_ok = bool(site and site.home.ok)
    conn.execute(
        "INSERT OR REPLACE INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, careers_url,"
        " job_link_count, job_titles, flags, breakdown, scored_at, home_title, home_excerpt)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (account_id, score.fit, score.signal, score.tier, int(home_ok), int(home_ok and is_dutch(site)),
         site.careers.url if site and site.careers and site.careers.ok else None,
         site.job_link_count if site else 0,
         json.dumps((site.job_titles if site else [])[:30], ensure_ascii=False),
         json.dumps(score.flags), json.dumps(score.breakdown), ts,
         site.home.title[:200] if home_ok else None,
         site.home.text[:1200] if home_ok else None))
    conn.execute("UPDATE accounts SET status=?, status_reason=? WHERE id=?",
                 (score.tier, score.reason, account_id))


def run(cfg: ClientConfig, conn, limit: int | None = None, rescore: bool = False, workers: int = 8,
        fetcher_factory=None, account_ids: list[int] | None = None) -> dict:
    fetcher_factory = fetcher_factory or default_fetcher
    if account_ids is not None:
        marks = ",".join("?" * len(account_ids)) or "NULL"
        accounts = [dict(r) for r in conn.execute(
            f"SELECT * FROM accounts WHERE client=? AND id IN ({marks}) ORDER BY id",
            (cfg.slug, *account_ids)).fetchall()]
    else:
        statuses = ("qualified_l1", "tier_1", "tier_2", "tier_3", "rejected_l2") if rescore else ("qualified_l1",)
        marks = ",".join("?" * len(statuses))
        accounts = [dict(r) for r in conn.execute(
            f"SELECT * FROM accounts WHERE client=? AND status IN ({marks}) ORDER BY id",
            (cfg.slug, *statuses)).fetchall()]
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
            site = SiteCrawl(home=Page(url=acc["website"], status=0, error=f"crawl_error:{type(exc).__name__}"))
        return acc, site

    summary = {"accounts": len(accounts), "tier_1": 0, "tier_2": 0, "tier_3": 0, "rejected_l2": 0,
               "unreachable": 0, "jev_decided": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, a) for a in accounts]
        for fut in as_completed(futures):
            acc, site = fut.result()
            jev = load_jev(conn, acc["id"])
            score, evidence = score_account(cfg, acc, site, jev)
            _save(conn, acc["id"], site, score, evidence)
            conn.commit()
            summary[score.tier] += 1
            summary["unreachable"] += any(f.startswith("unreachable") for f in score.flags)
            summary["jev_decided"] += jev is not None
    db.finish_run(conn, run_id, "succeeded", len(accounts), 0.0, json.dumps(summary))
    return summary
