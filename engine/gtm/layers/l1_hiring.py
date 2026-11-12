"""Layer 1, by signal: companies that have an open job for the role the offer replaces (BlitzAPI).

The first discovery path finds companies by industry and looks for signals afterwards, so most of
what it pays for has no signal. This path asks for the signal first: companies with a matching job
posted in the last N days, in the client's industries, size and countries (clients/<client>/hiring.yaml).
Accounts are stored like any Layer 1 account and still go through Layer 2: the crawl and Jev 1.14
confirm the open role on the company's own site before it is scored or quoted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from gtm import budget, db
from gtm.config import ClientConfig
from gtm.layers.l1_discover import SegmentResult, hard_filter, sync_exclusions
from gtm.normalize import country_code, member_count, normalize_domain, normalize_linkedin_company_url, size_range
from gtm.sources.blitz import BlitzClient

VENDOR = "blitzapi"
PRICE_KEY = "blitzapi:record"
PAGE = 50


@dataclass
class HiringPlan:
    name: str
    segment: str
    job: dict
    company: dict
    max_items: int
    est_cost: float


def load_config(cfg: ClientConfig) -> dict:
    with (Path(cfg.root) / "hiring.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def records_used(conn, client: str) -> int:
    """BlitzAPI records this client's runs have used this calendar month."""
    row = conn.execute("SELECT COALESCE(SUM(items), 0) FROM runs WHERE client=? AND vendor=?"
                       " AND substr(started_at, 1, 7)=strftime('%Y-%m', 'now') AND status='succeeded'",
                       (client, VENDOR)).fetchone()
    return int(row[0])


def check_records(conn, cfg: ClientConfig, wanted: int) -> None:
    """The plan is a flat fee for a number of records: stop before the month's allowance is passed."""
    cap = int(cfg.limits.month_budget_usd.get("blitzapi_records", 0))
    used = records_used(conn, cfg.slug)
    if used + wanted > cap:
        raise budget.BudgetExceeded(f"blitzapi: {wanted} records wanted, {used} of {cap} used this month "
                                    "(limits.yaml month_budget_usd.blitzapi_records).")


def plan(cfg: ClientConfig, names: list[str] | None = None, max_items: int | None = None) -> list[HiringPlan]:
    conf = load_config(cfg)
    job = {"title": {"include": conf["job_titles"]}, "date_posted": {"last_days": conf.get("posted_last_days", 30)}}
    if conf.get("job_countries"):
        job["location"] = {"country_code": {"include": conf["job_countries"]}}
    plans = []
    for s in conf["searches"]:
        if names and s["name"] not in names:
            continue
        if not names and not s.get("enabled", True):
            continue
        cfg.segment(s["segment"])          # the fit score needs a known segment
        company = {"employee_count": {"min": cfg.icp.company.employees_min, "max": cfg.icp.company.employees_max},
                   "hq": {"country_code": {"include": s.get("hq_countries") or cfg.icp.allowed_countries}}}
        if s.get("industries"):
            company["industry"] = {"include": s["industries"]}
        if s.get("keywords"):
            company["keywords"] = {"include": s["keywords"]}
        limit = max_items or s.get("max_items", 100)
        plans.append(HiringPlan(s["name"], s["segment"], job, company, limit, budget.estimate(cfg, PRICE_KEY, limit)))
    return plans


def normalise(company: dict, matched_jobs: int | None = None) -> dict:
    """One BlitzAPI company record in our account shape (same keys as l1_discover.normalise)."""
    start, end = size_range(company.get("size"))
    hq = company.get("hq") or {}
    website = company.get("website") or (f"https://{company['domain']}" if company.get("domain") else None)
    return {
        "linkedin_url": normalize_linkedin_company_url(company.get("linkedin_url")),
        "linkedin_id": str(company.get("linkedin_id") or "") or None,
        "name": str(company.get("name") or "").strip(),
        "website": website,
        "domain": normalize_domain(company.get("domain") or website),
        "country": country_code(hq.get("country_code")),
        "city": hq.get("city"),
        "industry": company.get("industry"),
        "employee_count": member_count(company.get("employees_on_linkedin")),
        "range_start": start,
        "range_end": end,
        "employee_range": f"{start or ''}-{end or ''}" if (start or end) else None,
        "raw": {"blitzapi": company, "matched_jobs": matched_jobs},
    }


def run(cfg: ClientConfig, conn, plans: list[HiringPlan], client: BlitzClient | None = None) -> list[SegmentResult]:
    sync_exclusions(conn, cfg)
    suppressed = {k: db.suppressed_values(conn, cfg.slug, k) for k in ("domain", "company", "linkedin")}
    results = []
    for p in plans:
        budget.check(conn, cfg, VENDOR, p.est_cost)
        check_records(conn, cfg, p.max_items)
        api = client or BlitzClient()
        res = SegmentResult(segment=p.name)
        run_id = db.start_run(conn, cfg.slug, "L1-hiring", VENDOR, p.name, p.est_cost, {"job": p.job, "company": p.company})
        cursor, items = None, []
        try:
            while len(items) < p.max_items:
                data = api.companies_hiring(p.job, p.company, min(PAGE, p.max_items - len(items)), cursor)
                page = data.get("results") or []
                items.extend(page)
                cursor = data.get("cursor")
                if not page or not cursor:
                    break
        except Exception as exc:
            db.finish_run(conn, run_id, "failed", len(items), None, str(exc)[:500])
            raise
        res.fetched = len(items)
        res.cost_usd = budget.estimate(cfg, PRICE_KEY, len(items))
        for item in items:
            acc = normalise(item.get("company") or {}, item.get("matched_jobs"))
            if not acc["name"]:
                res.rejected["no_name"] = res.rejected.get("no_name", 0) + 1
                continue
            reason = hard_filter(cfg, acc, suppressed)
            acc["source"] = f"blitzapi:companies-hiring:{p.name}"
            acc["status"] = "rejected_l1" if reason else "qualified_l1"
            acc["status_reason"] = reason
            if db.upsert_account(conn, cfg.slug, acc, p.segment) == "duplicate":
                res.duplicates += 1
                continue
            res.new += 1
            if reason:
                res.rejected[reason.split(":")[0]] = res.rejected.get(reason.split(":")[0], 0) + 1
            else:
                res.qualified += 1
        conn.commit()
        db.finish_run(conn, run_id, "succeeded", res.fetched, res.cost_usd,
                      f"records remaining on the plan: {api.records_remaining}")
        results.append(res)
    return results
