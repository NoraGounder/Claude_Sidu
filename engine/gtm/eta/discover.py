"""Find candidate companies on the Companies House register, by SIC code and age (eta.yaml `search`).

Each SIC code is one search. A run reads up to `max_per_code_per_run` companies per code and the next
run continues where it stopped (eta_progress), so the whole register for a code is covered over time
without reading anything twice. Holding vehicles, property and finance companies and dormant shells are
dropped by code and name before they cost any further request.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gtm.eta import store


@dataclass
class CodePlan:
    code: str
    label: str
    start_index: int
    max_items: int


@dataclass
class CodeResult:
    code: str
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    dropped: dict = field(default_factory=dict)
    hits: int | None = None
    exhausted: bool = False


def plan(eta: dict, conn, client: str, codes: list[str] | None = None, max_per_code: int | None = None) -> list[CodePlan]:
    search = eta.get("search", {})
    known = {str(k): v for k, v in (search.get("sic_codes") or {}).items()}
    wanted = [str(c) for c in codes] if codes else list(known)
    cap = max_per_code or int(search.get("max_per_code_per_run", 1000))
    plans = []
    for code in wanted:
        prog = store.progress(conn, client, code)
        if prog["exhausted"]:
            continue
        plans.append(CodePlan(code=code, label=known.get(code, code), start_index=int(prog["next_start"]), max_items=cap))
    return plans


def drop_reason(item: dict, eta: dict) -> str | None:
    exclude = eta.get("exclude", {})
    bad_codes = {str(c) for c in exclude.get("sic_codes", [])}
    sics = [str(s) for s in item.get("sic_codes") or []]
    if sics and sics[0] in bad_codes:
        return f"sic_{sics[0]}"
    name = (item.get("company_name") or "").lower()
    for word in exclude.get("name_keywords", []):
        if word.lower() in name:
            return "name_" + word.lower().replace(" ", "_")
    search = eta.get("search", {})
    cutoff = search.get("incorporated_to")
    created = item.get("date_of_creation")
    if cutoff and created and created > str(cutoff):
        return "too_young"
    if search.get("company_status") and item.get("company_status") not in (None, search["company_status"]):
        return f"status_{item.get('company_status')}"
    return None


def normalise(item: dict, code: str) -> dict:
    addr = item.get("registered_office_address") or {}
    return {
        "company_number": item["company_number"],
        "name": item.get("company_name") or item["company_number"],
        "company_status": item.get("company_status"),
        "company_type": item.get("company_type"),
        "incorporated": item.get("date_of_creation"),
        "sic_codes": [str(s) for s in item.get("sic_codes") or []],
        "search_code": code,
        "locality": addr.get("locality"),
        "postal_code": addr.get("postal_code"),
        "region": addr.get("region"),
    }


def run(ch, conn, client: str, eta: dict, plans: list[CodePlan]) -> list[CodeResult]:
    search = eta.get("search", {})
    page_size = int(search.get("page_size", 500))
    results = []
    for p in plans:
        res = CodeResult(code=p.code)
        start = p.start_index
        while res.fetched < p.max_items:
            size = min(page_size, p.max_items - res.fetched)
            data = ch.advanced_search(sic_codes=[p.code], company_status=search.get("company_status", "active"),
                                      company_type=search.get("company_type", "ltd"),
                                      incorporated_to=search.get("incorporated_to"), size=size, start_index=start)
            items = data.get("items") or []
            res.hits = data.get("hits", res.hits)
            for item in items:
                res.fetched += 1
                reason = drop_reason(item, eta)
                row = normalise(item, p.code)
                if reason:
                    row.update(stage="dropped", stage_reason=reason)
                    res.dropped[reason] = res.dropped.get(reason, 0) + 1
                outcome = store.upsert_company(conn, client, row)
                if outcome == "new" and not reason:
                    res.new += 1
                elif outcome == "duplicate":
                    res.duplicates += 1
            start += len(items)
            if len(items) < size or (res.hits is not None and start >= res.hits):
                res.exhausted = True
                break
        store.set_progress(conn, client, p.code, start, res.hits, res.exhausted)
        conn.commit()
        results.append(res)
    return results
