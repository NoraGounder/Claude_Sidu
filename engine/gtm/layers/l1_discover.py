"""Layer 1: discover target accounts with Harvest API's LinkedIn company search (on Apify).

Flow per segment: build search -> budget check -> run actor -> normalise -> hard filters ->
dedupe -> store. Nothing here costs money in --dry-run, and only company-level data is
collected (no people yet). People come in Layer 3, and only for accounts that pass Layer 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gtm import budget, db
from gtm.config import ClientConfig, Segment
from gtm.normalize import (country_code, has_keyword, member_count, normalize_domain,
                           normalize_linkedin_company_url, pick, size_range)
from gtm.sources.apify import ApifyClient, RunResult, load_fixture

ACTOR = "harvestapi/linkedin-company-search"
VENDOR = "apify"
PAGE_SIZE = 50          # companies per LinkedIn search page
MAX_PAGES = 20          # LinkedIn's limit per search


@dataclass
class SegmentPlan:
    segment: Segment
    actor_input: dict
    max_items: int
    price_key: str
    est_cost: float
    start_page: int = 1
    pages: int = 1


@dataclass
class SegmentResult:
    segment: str
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    qualified: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None


def plan(cfg: ClientConfig, segment_names: list[str] | None, max_items: int | None,
         mode: str = "full", conn=None) -> list[SegmentPlan]:
    """Full mode is the default: short mode has no website, size or headquarters country,
    and Layer 2 needs all three. Each segment continues from the page where its last live run
    stopped; a segment that has used all 20 LinkedIn pages is skipped (split it to go deeper)."""
    if segment_names:
        segments = [cfg.segment(n) for n in segment_names]
    else:
        segments = [s for s in cfg.icp.segments if s.enabled]
    plans = []
    for seg in segments:
        start = db.next_page(conn, cfg.slug, seg.name) if conn is not None else 1
        pages_left = MAX_PAGES - start + 1
        if pages_left <= 0:
            continue
        group = cfg.icp.industry_groups[seg.industry_group]
        limit = min(max_items or seg.max_items, PAGE_SIZE * pages_left)
        pages = -(-limit // PAGE_SIZE)
        actor_input = {
            "scraperMode": mode,
            "maxItems": limit,
            "locations": seg.locations,
            "industryIds": [str(i) for i in group.ids][:20],
            "companySize": cfg.icp.company.linkedin_company_sizes,
            "startPage": start,
            "takePages": pages,
        }
        if seg.search_query:
            actor_input["searchQuery"] = seg.search_query
        price_key = f"{ACTOR}:{mode}"
        plans.append(SegmentPlan(seg, actor_input, limit, price_key,
                                 budget.estimate(cfg, price_key, limit), start, pages))
    return plans


def exhausted_segments(cfg: ClientConfig, conn) -> list[str]:
    return [s.name for s in cfg.icp.segments
            if s.enabled and db.next_page(conn, cfg.slug, s.name) > MAX_PAGES]


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = pick(value, "name", "title", "label")
    return str(value) if value not in (None, "") else None


def normalise(item: dict) -> dict:
    """Map one Harvest company record to our account shape. Field names are read defensively
    because the actor's output can change; the raw record is always kept."""
    linkedin_url = normalize_linkedin_company_url(
        pick(item, "linkedinUrl", "url", "companyUrl", "linkedInUrl", "link"))
    website = pick(item, "website", "websiteUrl", "companyWebsite", "callToActionUrl")

    # Size: the company's stated band decides the ICP check; the member count is kept for reference.
    raw_count = pick(item, "employeeCount", "employeesCount", "staffCount", "employees")
    start, end = size_range(pick(item, "employeeCountRange", "companySize", "size"))
    if start is None and isinstance(raw_count, str):
        start, end = size_range(raw_count)

    hq = _headquarters(item)
    return {
        "linkedin_url": linkedin_url,
        "linkedin_id": str(pick(item, "id", "companyId", "universalName") or "") or None,
        "name": str(pick(item, "name", "companyName", "title") or "").strip(),
        "website": website,
        "domain": normalize_domain(website),
        "country": country_code(pick(hq, "countryCode", "country") if isinstance(hq, dict) else hq),
        "city": pick(hq, "city") if isinstance(hq, dict) else None,
        "industry": _text(pick(item, "industry", "industries.0.name", "industries.0")),
        "employee_count": member_count(raw_count),
        "range_start": start,
        "range_end": end,
        "employee_range": f"{start or ''}-{end or ''}" if (start or end) else None,
        "raw": item,
    }


def _headquarters(item: dict):
    """The headquarters entry, never just the first office listed."""
    locations = item.get("locations")
    if isinstance(locations, list) and locations:
        for loc in locations:
            if isinstance(loc, dict) and loc.get("headquarter"):
                return loc
        return None   # offices listed but none marked as HQ: country unknown, Layer 2 decides
    hq = pick(item, "headquarter", "headquarters", "hq")
    if hq:
        return hq
    location = item.get("location")
    if isinstance(location, dict):
        return location.get("linkedinText") or location
    return location


def size_ok(acc: dict, employees_min: int, employees_max: int) -> bool:
    start, end = acc.get("range_start"), acc.get("range_end")
    if start or end:
        low, high = start or end, end or start
        return high >= employees_min and low <= employees_max
    count = acc.get("employee_count")
    return count is None or employees_min <= count <= employees_max


def hard_filter(cfg: ClientConfig, acc: dict, suppressed: dict[str, set[str]]) -> str | None:
    """Return a rejection reason, or None if the account passes Layer 1."""
    if not acc["name"]:
        return "no_name"
    kw = has_keyword(acc["name"], cfg.icp.exclusions.name_keywords)
    if kw:
        return f"excluded_keyword:{kw}"
    if acc["domain"] and (acc["domain"] in suppressed["domain"]
                          or acc["domain"] in {d.lower() for d in cfg.icp.exclusions.domains}):
        return "suppressed_domain"
    if acc["linkedin_url"] and acc["linkedin_url"] in suppressed["linkedin"]:
        return "suppressed_linkedin"
    if acc["name"].lower() in suppressed["company"]:
        return "suppressed_company"
    if acc["country"] and acc["country"] not in cfg.icp.allowed_countries:
        return f"country:{acc['country']}"
    rules = cfg.icp.company
    if not size_ok(acc, rules.employees_min, rules.employees_max):
        return "size_out_of_range"
    return None


def sync_exclusions(conn, cfg: ClientConfig) -> int:
    rows = cfg.exclusion_rows()
    for row in rows:
        kind = row.get("kind", "").strip().lower()
        value = row["value"].strip()
        if kind == "linkedin":
            value = normalize_linkedin_company_url(value) or value
        if kind == "domain":
            value = normalize_domain(value) or value
        if kind in {"domain", "company", "linkedin", "email"}:
            db.add_suppression(conn, cfg.slug, kind, value, row.get("reason", ""))
    conn.commit()
    return len(rows)


def run(cfg: ClientConfig, conn, plans: list[SegmentPlan], fixture: str | None = None,
        client: ApifyClient | None = None) -> list[SegmentResult]:
    sync_exclusions(conn, cfg)
    suppressed = {k: db.suppressed_values(conn, cfg.slug, k) for k in ("domain", "company", "linkedin")}
    results = []
    for p in plans:
        res = SegmentResult(segment=p.segment.name)
        if fixture:
            outcome: RunResult = load_fixture(fixture)
            run_id = db.start_run(conn, cfg.slug, "L1", VENDOR, f"{p.segment.name} (fixture)", 0.0, p.actor_input)
        else:
            budget.check(conn, cfg, VENDOR, p.est_cost)
            run_id = db.start_run(conn, cfg.slug, "L1", VENDOR, p.segment.name, p.est_cost, p.actor_input)
            try:
                outcome = (client or ApifyClient()).run_actor(ACTOR, p.actor_input)
            except Exception as exc:
                db.finish_run(conn, run_id, "failed", 0, None, str(exc)[:500])
                raise
        res.fetched = len(outcome.items)
        # Apify's reported usage leaves out pay-per-result charges, so take the larger of the
        # reported cost and results x list price.
        priced = len(outcome.items) * cfg.limits.unit_price_usd.get(p.price_key, 0.0)
        res.cost_usd = 0.0 if fixture else round(max(outcome.cost_usd or 0.0, priced), 4)
        for item in outcome.items:
            acc = normalise(item)
            reason = hard_filter(cfg, acc, suppressed)
            acc["source"] = f"harvestapi:linkedin-company-search:{p.segment.name}"
            acc["status"] = "rejected_l1" if reason else "qualified_l1"
            acc["status_reason"] = reason
            if not acc["name"]:
                res.rejected["no_name"] = res.rejected.get("no_name", 0) + 1
                continue
            outcome_kind = db.upsert_account(conn, cfg.slug, acc, p.segment.name)
            if outcome_kind == "duplicate":
                res.duplicates += 1
                continue
            res.new += 1
            if reason:
                key = reason.split(":")[0]
                res.rejected[key] = res.rejected.get(key, 0) + 1
            else:
                res.qualified += 1
        conn.commit()
        db.finish_run(conn, run_id, "succeeded", res.fetched, res.cost_usd)
        if not fixture:
            db.set_next_page(conn, cfg.slug, p.segment.name, p.start_page + p.pages)
        results.append(res)
    return results
