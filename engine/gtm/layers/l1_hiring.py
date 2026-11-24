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
RERUN_DAYS = 7     # job postings are listed for weeks: a repeat within a week returns the same companies


def recently_run(conn, client: str, days: int = RERUN_DAYS) -> set[str]:
    """Searches that succeeded in the last `days` days. Re-running them spends records on companies we
    already have, so the CLI skips them unless asked (--force)."""
    rows = conn.execute("SELECT label FROM runs WHERE client=? AND vendor=? AND layer='L1-hiring' AND status='succeeded'"
                        " AND started_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)", (client, VENDOR, f"-{days} days"))
    return {r[0] for r in rows}


@dataclass
class HiringPlan:
    name: str
    segment: str
    job: dict
    company: dict
    max_items: int
    est_cost: float
    kind: str = "hiring"        # "hiring": companies with a matching job posting; "companies": firmographics only


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


def plan_companies(cfg: ClientConfig, names: list[str] | None = None, max_items: int | None = None) -> list[HiringPlan]:
    """Layer 1 by firmographics on the flat plan (hiring.yaml `company_searches`): the same filters as the
    hiring searches (industries, keywords, HQ countries, the ICP's size band) without the job condition. It
    replaces the paid industry searches on Apify; Layer 2 still crawls, scores and asks Jev about every company."""
    conf = load_config(cfg)
    plans = []
    for s in conf.get("company_searches") or []:
        if names and s["name"] not in names:
            continue
        if not names and not s.get("enabled", True):
            continue
        cfg.segment(s["segment"])
        company = {"employee_count": {"min": cfg.icp.company.employees_min, "max": cfg.icp.company.employees_max},
                   "hq": {"country_code": {"include": s.get("hq_countries") or cfg.icp.allowed_countries}}}
        if s.get("industries"):
            company["industry"] = {"include": s["industries"]}
        if s.get("keywords"):
            company["keywords"] = {"include": s["keywords"]}
        limit = max_items or s.get("max_items", 100)
        plans.append(HiringPlan(s["name"], s["segment"], {}, company, limit,
                                budget.estimate(cfg, PRICE_KEY, limit), kind="companies"))
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
                n = min(PAGE, p.max_items - len(items))
                data = (api.search_companies(p.company, n, cursor) if p.kind == "companies"
                        else api.companies_hiring(p.job, p.company, n, cursor))
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
            acc = (normalise(item) if p.kind == "companies"
                   else normalise(item.get("company") or {}, item.get("matched_jobs")))
            if not acc["name"]:
                res.rejected["no_name"] = res.rejected.get("no_name", 0) + 1
                continue
            reason = hard_filter(cfg, acc, suppressed)
            acc["source"] = f"blitzapi:{'company-search' if p.kind == 'companies' else 'companies-hiring'}:{p.name}"
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


# ---------- job postings as evidence (opt-in: hiring.yaml `postings`) ----------

POSTING_SIGNAL = "job_posting"


def fetch_postings(cfg: ClientConfig, conn, max_postings: int | None = None,
                   client: BlitzClient | None = None) -> dict:
    """The live job postings behind the hiring searches (BlitzAPI jobs search, one record per posting),
    stored as Layer 1 evidence on the accounts we already have: title, posting URL, date and place.
    Layer 2 adds these titles to the ones it reads on the company's own site (scoring.yaml
    `posted_jobs: true`), so a vacancy listed only on a job board still counts once Jev 1.14 has
    confirmed the title is the kind of role the offer replaces."""
    conf = load_config(cfg)
    limit = max_postings or int(conf.get("postings", {}).get("max_postings", 300))
    plans = plan(cfg)
    industries = sorted({i for p in plans for i in (p.company.get("industry") or {}).get("include", [])})
    countries = sorted({c for p in plans for c in p.company["hq"]["country_code"]["include"]})
    job = plans[0].job if plans else {}
    company = {"employee_count": plans[0].company["employee_count"], "hq": {"country_code": {"include": countries}}}
    # hiring.yaml postings.any_industry: match postings to accounts we already have whatever industry
    # label BlitzAPI gives them (LinkedIn labels differ from the ones our discovery used).
    if industries and not conf.get("postings", {}).get("any_industry"):
        company["industry"] = {"include": industries}
    check_records(conn, cfg, limit)
    api = client or BlitzClient()
    run_id = db.start_run(conn, cfg.slug, "L1-hiring", VENDOR, "postings", 0.0, {"job": job, "company": company})
    postings, cursor = [], None
    try:
        while len(postings) < limit:
            data = api.jobs(job, company, min(PAGE, limit - len(postings)), cursor)
            page = data.get("results") or []
            postings.extend(page)
            cursor = data.get("cursor")
            if not page or not cursor:
                break
    except Exception as exc:
        db.finish_run(conn, run_id, "failed", len(postings), 0.0, str(exc)[:300])
        raise
    by_url = {normalize_linkedin_company_url(r["linkedin_url"]): r["id"] for r in conn.execute(
        "SELECT id, linkedin_url FROM accounts WHERE client=? AND linkedin_url IS NOT NULL", (cfg.slug,))}
    ts = db.now_iso()
    matched: dict[int, int] = {}
    for p in postings:
        acc_id = by_url.get(normalize_linkedin_company_url(p.get("company_linkedin_url")))
        title = str(p.get("title") or "").strip()
        if not acc_id or not title:
            continue
        loc = p.get("location") or {}
        place = loc.get("city") or loc.get("country_code") or "" if isinstance(loc, dict) else str(loc)
        if matched.get(acc_id) == 0 or acc_id not in matched:
            conn.execute("DELETE FROM evidence WHERE account_id=? AND layer='L1' AND signal=?", (acc_id, POSTING_SIGNAL))
            matched[acc_id] = 0
        matched[acc_id] += 1
        conn.execute("INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
                     (acc_id, "L1", POSTING_SIGNAL, title[:200], p.get("url") or "",
                      f"{title} (posted {str(p.get('date_posted') or '')[:10]}{', ' + place if place else ''})", ts))
    conn.commit()
    db.finish_run(conn, run_id, "succeeded", len(postings), 0.0,
                  f"{len(matched)} known accounts with postings; records remaining {api.records_remaining}")
    return {"postings": len(postings), "accounts": len(matched), "account_ids": sorted(matched)}


def posted_jobs(conn, account_id: int) -> dict[str, str]:
    """Posting titles stored for an account, with the posting URL: {title: url}."""
    rows = conn.execute("SELECT label, url FROM evidence WHERE account_id=? AND layer='L1' AND signal=?"
                        " ORDER BY id", (account_id, POSTING_SIGNAL))
    return {r["label"]: r["url"] for r in rows}
