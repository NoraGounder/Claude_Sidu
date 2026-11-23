"""United States: who leads each shortlisted company, and roughly how old they are and how long they have led it.

US registers carry no owner ages. FullEnrich's people search (paid, about $0.014 per person returned) takes the
company's verified website domain (sieve 2) and senior titles, and returns each person's work history with start
dates and education with start and end dates. From those:

    age        ~ today - (first degree start - 18), or today - (first degree end - 22), or at least
                 today - (first job start - 22)   (LinkedIn histories are often cut short, so this is a floor)
    tenure     = start of the current role at this company

Both are estimates: the ledger marks them "unverified" until the owner confirms. Names, titles and estimated birth
years stay in data/engine.db (gitignored). The budget guard and the runs ledger cover every paid call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from gtm import budget, db
from gtm.eta import store

VENDOR = "fullenrich"
PRICE_KEY = "fullenrich:person_returned"
TITLES = ["Owner", "President", "CEO", "Chief Executive Officer", "Founder", "Principal", "Managing Partner",
          "Chairman"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_owner_lookups (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    domain          TEXT NOT NULL,
    people_found    INTEGER NOT NULL,
    credits         REAL,
    looked_up_at    TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def domain_of(website: str) -> str:
    host = website.split("://", 1)[-1].split("/", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def targets(conn, client: str, limit: int | None = None, verdicts=("qualified", "watch")) -> list[dict]:
    """US companies with a verified website (sieve 2) and no owner lookup yet, best sieve-1 score first."""
    ensure_schema(conn)
    marks = ",".join("?" for _ in verdicts)
    rows = conn.execute(
        f"SELECT c.company_number, c.name, w.website, s1.score FROM eta_companies c"
        f" JOIN eta_websites w ON w.client=c.client AND w.company_number=c.company_number AND w.website IS NOT NULL"
        f" JOIN eta_screen s2 ON s2.client=c.client AND s2.company_number=c.company_number AND s2.sieve=2"
        f" AND s2.verdict IN ({marks})"
        f" JOIN eta_screen s1 ON s1.client=c.client AND s1.company_number=c.company_number AND s1.sieve=1"
        f" LEFT JOIN eta_owner_lookups o ON o.client=c.client AND o.company_number=c.company_number"
        f" WHERE c.client=? AND c.company_number LIKE 'US-%' AND o.company_number IS NULL"
        f" ORDER BY s1.score DESC", (*verdicts, client)).fetchall()
    out = [dict(r) | {"domain": domain_of(r["website"])} for r in rows]
    return out[:limit] if limit else out


def search_body(domain: str, per_company: int) -> dict:
    """The request FullEnrich receives (shown in the dry run)."""
    return {"limit": per_company,
            "current_company_domains": [{"value": domain, "exact_match": True, "exclude": False}],
            "current_position_titles": [{"value": t, "exact_match": False, "exclude": False} for t in TITLES]}


# ---------- age and tenure ----------

def _year(text: str | None) -> int | None:
    try:
        return int(str(text)[:4]) if text else None
    except ValueError:
        return None


@dataclass
class AgeEstimate:
    age: int | None
    basis: str
    floor: bool            # True when the age is only a lower bound
    tenure_since: int | None


def estimate(person: dict, domain: str, today: date) -> AgeEstimate:
    educations = person.get("educations") or []
    starts = [y for y in (_year(e.get("start_at")) for e in educations) if y]
    ends = [y for y in (_year(e.get("end_at")) for e in educations) if y]
    jobs = ((person.get("employment") or {}).get("all") or [])
    job_starts = [y for y in (_year(j.get("start_at")) for j in jobs) if y]
    tenure = None
    for j in jobs:
        company = j.get("company") or {}
        if j.get("is_current") and domain in str(company.get("domain") or company.get("website") or ""):
            tenure = _year(j.get("start_at"))
    if tenure is None:
        current = (person.get("employment") or {}).get("current") or {}
        tenure = _year(current.get("start_at"))
    if starts:
        return AgeEstimate(today.year - (min(starts) - 18), "first degree started at about 18", False, tenure)
    if ends:
        return AgeEstimate(today.year - (min(ends) - 22), "first degree finished at about 22", False, tenure)
    if job_starts:
        return AgeEstimate(today.year - (min(job_starts) - 22), "first listed job at about 22 (a floor)", True, tenure)
    return AgeEstimate(None, "no dated history", True, tenure)


_NOT_TOP = ("vice", "vp", "assistant", "associate", "deputy", "regional", "division", "branch", "sales",
            "office manager", "project")


def title_rank(title: str | None) -> int:
    """0 owner/founder, 1 president/CEO, 2 principal/chairman/managing partner, 9 anyone else.
    'Vice President', 'Assistant to the President', 'Project Principal' and the like are never the owner."""
    t = f" {(title or '').lower()} "
    if any(w in t for w in _NOT_TOP):
        return 9
    for rank, words in enumerate((("owner", "founder"), ("president", " ceo", "chief executive"),
                                  ("principal", "managing partner", "chairman"))):
        if any(w in t for w in words):
            return rank
    return 9


def _is_owner(person: dict) -> int:
    current = (person.get("employment") or {}).get("current") or {}
    return title_rank(current.get("title"))


def summarize(conn, client: str, number: str, today: date) -> dict | None:
    """Write the ledger's owner claims from the people stored for this company: the top-ranked leader only.
    Re-runnable at no cost (eta-owners --resummarize)."""
    people = [dict(r) for r in conn.execute(
        "SELECT name, role, birth_year, appointed_on, source FROM eta_owners WHERE client=? AND company_number=?"
        " AND source LIKE 'fullenrich%'", (client, number))]
    conn.execute("DELETE FROM eta_evidence WHERE client=? AND company_number=? AND claim IN"
                 " ('Owner age (estimate)', 'Leader since', 'Owner or CEO found')", (client, number))
    people.sort(key=lambda p: (title_rank(p["role"]), -(today.year - p["birth_year"]) if p["birth_year"] else 0))
    top = people[0] if people and title_rank(people[0]["role"]) <= 2 else None
    put = lambda claim, value, status, step=None: store.record_evidence(
        conn, client, number, claim, value, status, "FullEnrich work history", step)
    if not top:
        put("Owner or CEO found", "no" if people else "no people", "unknown",
            "Ask the owner's name from the website, state registry or the Form 5500 signer")
        put("Owner age (estimate)", None, "unknown", "Ask the owner")
        return None
    age = today.year - top["birth_year"] if top["birth_year"] else None
    floor = "(a floor)" in (top["source"] or "")
    if age is not None and floor and age < 35:
        age = None                       # a history that starts recently says nothing about age
    put("Owner or CEO found", top["role"], "unverified")
    put("Owner age (estimate)", None if age is None else f"{'at least' if floor else 'about'} {age} ({top['role']})",
        "unverified" if age is not None else "unknown", "Confirm with the owner")
    if top["appointed_on"]:
        put("Leader since", top["appointed_on"], "unverified", "Confirm with the owner")
    return {"role": top["role"], "age": age, "floor": floor, "since": top["appointed_on"]}


# ---------- run ----------

def plan(conn, cfg, limit: int | None, per_company: int, verdicts=("qualified", "watch")) -> dict:
    rows = targets(conn, cfg.slug, limit, verdicts)
    max_people = len(rows) * per_company
    est = budget.estimate(cfg, PRICE_KEY, max_people)
    cap = cfg.limits.month_budget_usd.get(VENDOR)
    spent = db.month_spend(conn, cfg.slug, VENDOR)
    return {"companies": len(rows), "max_people": max_people, "max_credits": max_people * 0.25,
            "estimate_usd": est, "cap_usd": cap, "spent_usd": spent, "rows": rows}


def run(conn, cfg, fe, limit: int | None = None, per_company: int = 3, today: date | None = None,
        verdicts=("qualified", "watch")) -> dict:
    today = today or date.today()
    p = plan(conn, cfg, limit, per_company, verdicts)
    budget.check(conn, cfg, VENDOR, p["estimate_usd"])
    out = {"companies": 0, "with_people": 0, "people": 0, "credits": 0.0, "ages": 0}
    run_id = db.start_run(conn, cfg.slug, "eta_owners", VENDOR, "US owner lookup", p["estimate_usd"],
                          {"limit": limit, "per_company": per_company})
    try:
        for row in p["rows"]:
            result = fe.search_people(row["domain"], TITLES, limit=per_company)
            out["companies"] += 1
            out["credits"] += result.credits
            people = sorted(result.people, key=_is_owner)
            for person in people:
                est = estimate(person, row["domain"], today)
                current = (person.get("employment") or {}).get("current") or {}
                name = person.get("full_name") or " ".join(x for x in (person.get("first_name"), person.get("last_name")) if x)
                store.save_owner(conn, cfg.slug, row["company_number"], {
                    "person_key": f"fullenrich:{person.get('id') or name}", "kind": "director", "name": name,
                    "role": current.get("title"), "birth_year": today.year - est.age if est.age else None,
                    "birth_month": None, "appointed_on": str(est.tenure_since) if est.tenure_since else None,
                    "ceased_on": None, "ownership": None,
                    "source": f"fullenrich people search ({row['domain']}); age: {est.basis}"})
            top = summarize(conn, cfg.slug, row["company_number"], today)
            out["leaders"] = out.get("leaders", 0) + bool(top)
            out["ages"] += bool(top and top["age"] is not None)
            out["people"] += len(people)
            out["with_people"] += bool(people)
            conn.execute("INSERT OR REPLACE INTO eta_owner_lookups(client, company_number, domain, people_found,"
                         " credits, looked_up_at) VALUES (?,?,?,?,?,?)",
                         (cfg.slug, row["company_number"], row["domain"], len(people), result.credits, db.now_iso()))
            conn.commit()
    finally:
        cost = round(out["credits"] * budget.estimate(cfg, "fullenrich:credit", 1), 4)
        db.finish_run(conn, run_id, "ok", out["people"], cost, json.dumps(out))
        conn.commit()
    out["cost_usd"] = cost
    return out
