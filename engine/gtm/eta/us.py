"""United States: discovery and sieve 1 from Form 5500 filings (current) and the SBA's PPP file (2020-21).

The US has no public register of private-company accounts. The SBA's PPP file (loans of $150k+, 2020-21,
public domain, free) lists every borrower with its NAICS code, jobs reported, loan amount, business type and
age. A first-draw loan was 2.5 months of payroll, so it is a payroll measure, and payroll over the industry's
payroll share of revenue gives a revenue estimate. Everything derived here is an estimate and goes into the
evidence ledger as "unverified": the real numbers come from the seller.

    download -> stream + prefilter (NAICS, jobs, entity, size) -> one row per borrower -> eta_companies
    -> sieve 1 on the proxies -> eta_screen (sieve 1), then sieve 2 (qualify.py) as for the UK

The file is cached once in data/eta/sba/ (about 450 MB). Race, ethnicity, gender and veteran fields are
never read into the database.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

from gtm.config import data_dir
from gtm.eta import store

SOURCE = "sba:ppp_foia"
DATASET_URL = "https://data.sba.gov/dataset/ppp-foia"
DOL_PAGE = "https://www.dol.gov/agencies/ebsa/about-ebsa/our-activities/public-disclosure/foia/form-5500-datasets"


def cache_path() -> Path:
    path = data_dir() / "eta" / "sba"
    path.mkdir(parents=True, exist_ok=True)
    return path / "ppp_150k_plus.csv"


def download(url: str, dest: Path | None = None, session=None) -> Path:
    """Fetch the file once (resumes nothing: a partial file is replaced)."""
    dest = dest or cache_path()
    if dest.exists() and dest.stat().st_size > 100_000_000:
        return dest
    tmp = dest.with_suffix(".part")
    http = session or requests
    with http.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    return dest


# ---------- estimates ----------

def payroll_share(naics: str, shares: dict) -> float:
    best = None
    for prefix, share in (shares or {}).items():
        if naics.startswith(str(prefix)) and (best is None or len(str(prefix)) > len(best[0])):
            best = (str(prefix), float(share))
    return best[1] if best else 0.30


def _money(text: str | None) -> float:
    try:
        return float((text or "0").replace(",", "") or 0)
    except ValueError:
        return 0.0


def _int(text: str | None) -> int:
    try:
        return int(float(text or 0))
    except ValueError:
        return 0


def borrower_key(name: str, zip_code: str) -> str:
    core = re.sub(r"\b(inc|llc|corp|corporation|co|company|ltd|the|l l c|pc|pllc)\b", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", "", core) + ":" + (zip_code or "")[:5]


@dataclass
class Borrower:
    company_id: str
    name: str
    naics: str
    city: str
    state: str
    zip5: str
    business_type: str
    business_age: str
    jobs: int
    first_draw: float
    second_draw: float
    forgiven: float
    loan_status: str
    date_approved: str
    lender: str
    loans: list[str] = field(default_factory=list)
    payroll_est: float = 0.0
    revenue_est: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def stream(path: Path, us: dict):
    """Yield one Borrower per company that clears the prefilter, merging first and second draws."""
    pre = us.get("prefilter") or {}
    codes = {str(c) for c in (us.get("naics_codes") or {})}
    types = set(pre.get("business_types") or [])
    states = set(pre.get("states") or [])
    shares, multiple = us.get("payroll_share") or {}, float(us.get("payroll_multiple", 4.8))
    merged: dict[str, Borrower] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            naics = (row.get("NAICSCode") or "").strip()
            if codes and naics not in codes:
                continue
            if (row.get("NonProfit") or "").strip().upper() == "Y" or (row.get("FranchiseName") or "").strip():
                continue
            if types and (row.get("BusinessType") or "").strip() not in types:
                continue
            state = (row.get("BorrowerState") or row.get("ProjectState") or "").strip()
            if states and state not in states:
                continue
            zip5 = (row.get("BorrowerZip") or "")[:5]
            key = borrower_key(row.get("BorrowerName", ""), zip5)
            amount = _money(row.get("CurrentApprovalAmount"))
            second = (row.get("ProcessingMethod") or "").strip() == "PPS"
            b = merged.get(key)
            if b is None:
                b = merged[key] = Borrower(
                    company_id=f"US-{row.get('LoanNumber')}", name=(row.get("BorrowerName") or "").strip(),
                    naics=naics, city=(row.get("BorrowerCity") or "").strip(), state=state, zip5=zip5,
                    business_type=(row.get("BusinessType") or "").strip(),
                    business_age=(row.get("BusinessAgeDescription") or "").strip(), jobs=0, first_draw=0.0,
                    second_draw=0.0, forgiven=0.0, loan_status=(row.get("LoanStatus") or "").strip(),
                    date_approved=(row.get("DateApproved") or "").strip(),
                    lender=(row.get("OriginatingLender") or "").strip())
            b.loans.append(row.get("LoanNumber") or "")
            b.jobs = max(b.jobs, _int(row.get("JobsReported")))
            b.forgiven += _money(row.get("ForgivenessAmount"))
            if second:
                b.second_draw = max(b.second_draw, amount)
            else:
                b.first_draw = max(b.first_draw, amount)
                b.company_id = f"US-{row.get('LoanNumber')}"
                b.business_age = (row.get("BusinessAgeDescription") or b.business_age).strip()
    for b in merged.values():
        base = b.first_draw or b.second_draw
        b.payroll_est = round(base * multiple)
        b.revenue_est = round(b.payroll_est / payroll_share(b.naics, shares))
        if not (pre.get("jobs_min", 0) <= b.jobs <= pre.get("jobs_max", 10**9)):
            continue
        if b.revenue_est < pre.get("revenue_estimate_min_usd", 0):
            continue
        yield b


# ---------- one candidate = a Form 5500 employer, a PPP borrower, or both ----------

@dataclass
class Candidate:
    company_id: str
    name: str
    naics: str
    city: str
    state: str
    zip5: str
    headcount: int
    headcount_source: str            # "form5500 2024" or "ppp 2020-21"
    revenue_est: float
    revenue_basis: str
    employer: object | None = None   # dol.Employer
    borrower: Borrower | None = None

    @property
    def sources(self) -> list[str]:
        return [x for x, v in (("form5500", self.employer), ("ppp", self.borrower)) if v]

    def metrics(self) -> dict:
        e, b = self.employer, self.borrower
        return {"naics": self.naics, "headcount": self.headcount, "headcount_source": self.headcount_source,
                "revenue_est": self.revenue_est, "revenue_basis": self.revenue_basis, "sources": self.sources,
                "plan_since": e.plan_since if e else None, "active_before": e.active_before if e else None,
                "years_compared": list(e.years_compared) if e else None, "final_filing": e.final_filing if e else None,
                "ppp_jobs": b.jobs if b else None, "ppp_payroll_est": b.payroll_est if b else None,
                "second_draw": b.second_draw if b else None, "business_age": b.business_age if b else None,
                "business_type": b.business_type if b else None}


def revenue_per_employee(naics: str, table: dict) -> float:
    best = None
    for prefix, value in (table or {}).items():
        if naics.startswith(str(prefix)) and (best is None or len(str(prefix)) > len(best[0])):
            best = (str(prefix), float(value))
    return best[1] if best else 150_000.0


def combine(employers: dict, borrowers: list[Borrower], us: dict) -> list[Candidate]:
    """Join Form 5500 employers and PPP borrowers on name + ZIP; keep both kinds."""
    shares, rpe = us.get("payroll_share") or {}, us.get("revenue_per_employee") or {}
    wage_growth = float(us.get("wage_growth_since_2020", 1.2))
    by_key = {}
    for b in borrowers:
        by_key.setdefault(borrower_key(b.name, b.zip5), b)
    used, out = set(), []
    for e in employers.values():
        b = by_key.get(borrower_key(e.name, e.zip5)) or (by_key.get(borrower_key(e.dba, e.zip5)) if e.dba else None)
        if b:
            used.add(id(b))
        head = e.active or (b.jobs if b else 0)
        typical = head * revenue_per_employee(e.naics, rpe)
        if b and b.jobs:
            pay_head = b.payroll_est / b.jobs * wage_growth
            from_pay = pay_head * head / payroll_share(e.naics, shares)
            # PPP jobs are often under-reported, which inflates pay per head: blend with the industry norm and
            # keep the result inside a sane band around it
            lo, hi = (float(x) for x in us.get("revenue_clamp", [0.6, 1.6]))
            revenue = min(max((from_pay + typical) / 2, typical * lo), typical * hi)
            basis = "mean of (PPP pay per head x 2024 headcount / payroll share) and (2024 headcount x industry revenue per employee), clamped"
        else:
            revenue = typical
            basis = "2024 headcount x industry revenue per employee"
        out.append(Candidate(f"US-{e.ein}", e.name, e.naics, e.city, e.state, e.zip5, head,
                             f"form5500 {e.year}", round(revenue), basis, e, b))
    for b in borrowers:
        if id(b) not in used:
            out.append(Candidate(b.company_id, b.name, b.naics, b.city, b.state, b.zip5, b.jobs, "ppp 2020-21",
                                 b.revenue_est, "PPP payroll / industry payroll share (2020)", None, b))
    return out


# ---------- sieve 1 ----------

def hard_fails(c: Candidate, hard: dict) -> list[str]:
    fails = []
    if c.revenue_est < hard.get("revenue_min_usd", 0):
        fails.append("too_small_revenue_estimate")
    if c.revenue_est > hard.get("revenue_max_usd", 10**12):
        fails.append("too_large_revenue_estimate")
    if c.headcount < hard.get("jobs_min", 0):
        fails.append("too_few_employees")
    if c.headcount > hard.get("jobs_max", 10**9):
        fails.append("too_many_employees")
    if c.employer and c.employer.final_filing:
        fails.append("plan_ended_final_filing")
    age = (c.borrower.business_age if c.borrower else "").lower()
    if hard.get("exclude_change_of_ownership", True) and "change of ownership" in age:
        fails.append("recent_change_of_ownership")
    if age.startswith(("new business", "startup")) and not (c.employer and c.employer.plan_since
                                                             and c.employer.plan_since <= 2015):
        fails.append("short_history")
    return fails


def components(c: Candidate, bars: dict, weights: dict) -> dict[str, float]:
    lo, hi = bars.get("revenue_target_usd", [10e6, 30e6])
    clo, chi = bars.get("revenue_core_usd", [12e6, 25e6])
    jlo, jhi = bars.get("jobs_target", [20, 200])
    e, b = c.employer, c.borrower
    since = e.plan_since if e else None
    if e and e.active_before:
        ratio = e.active / e.active_before
        growth = 1.0 if ratio >= 1.0 else 0.8 if ratio >= 0.9 else 0.4 if ratio >= 0.75 else 0.1
    else:
        growth = 0.5
    pay = (b.payroll_est / b.jobs) if b and b.jobs else None
    out = {
        "size": 1.0 if clo <= c.revenue_est <= chi else 0.7 if lo <= c.revenue_est <= hi else 0.3,
        "jobs": 1.0 if jlo <= c.headcount <= jhi else 0.4,
        "longevity": (1.0 if since and since <= bars.get("plan_since_long", 2000)
                      else 0.6 if since and since <= bars.get("plan_since_mid", 2010) else 0.3),
        "growth": growth,
        "evidence": 1.0 if len(c.sources) == 2 else 0.5,
        "resilience": 0.3 if b and b.second_draw else 1.0 if b else 0.8,
        "skilled_pay": min(pay / bars.get("payroll_per_job_good_usd", 50000), 1.0) if pay else 0.5,
    }
    return {k: round(v * float(weights.get(k, 0)), 1) for k, v in out.items()}


def evaluate(c: Candidate, sieve: dict) -> tuple[str, float, list[str], dict]:
    fails = hard_fails(c, sieve.get("hard") or {})
    breakdown = components(c, sieve.get("bars") or {}, sieve.get("weights") or {})
    score = round(sum(breakdown.values()), 1)
    if fails:
        return "fail", score, fails, breakdown
    verdict = "pass" if score >= sieve.get("pass", 60) else "review" if score >= sieve.get("review", 40) else "fail"
    return verdict, score, fails, breakdown


def ledger(conn, client: str, c: Candidate, band: float) -> None:
    e, b = c.employer, c.borrower
    def put(claim, value, status, source, step=None):
        store.record_evidence(conn, client, c.company_id, claim, value, status, source, step)
    if e:
        src = f"{DOL_PAGE} (Form 5500 plan year {e.year}, EIN {e.ein})"
        put(f"Active plan participants ({e.year})", str(e.active), "public", src)
        if e.active_before is not None:
            put(f"Active plan participants ({e.years_compared[0]})", str(e.active_before), "public", src)
        put("Retirement plan since", str(e.plan_since) if e.plan_since else None, "public" if e.plan_since else "unknown", src)
    if b:
        src = f"{DATASET_URL} (loans {', '.join(x for x in b.loans if x)})"
        put("Jobs reported (PPP, 2020-21)", str(b.jobs), "public", src)
        put("PPP first-draw loan", f"${b.first_draw:,.0f}", "public", src)
        if b.second_draw:
            put("PPP second-draw loan", f"${b.second_draw:,.0f} (needed a 25% revenue fall in 2020)", "public", src)
        put("Business age (PPP)", b.business_age, "public", src)
    put("Revenue (estimate)", f"${c.revenue_est * (1 - band):,.0f} - ${c.revenue_est * (1 + band):,.0f}",
        "unverified", c.revenue_basis, "Three years of tax returns and P&L from the seller")
    for claim in ("EBITDA", "Owner age", "Owner earnings", "Customer concentration", "Recurring revenue"):
        put(claim, None, "unknown", None, "Ask the owner or broker")


def save_signer(conn, client: str, company_id: str, e) -> bool:
    if not e.signer:
        return False
    store.save_owner(conn, client, company_id, {
        "person_key": f"form5500:signer:{e.ein}", "kind": "director", "name": e.signer,
        "role": f"signed the {e.year} Form 5500 for the employer", "birth_year": None, "birth_month": None,
        "appointed_on": None, "ceased_on": None, "ownership": None, "source": f"{DOL_PAGE} (EIN {e.ein})"})
    return True


# Claims written by sieve 2 and the owner lookup (paid or Jev-decided): a US rebuild keeps them.
KEEP_CLAIMS = ("7 Powers:%", "Stanford industry score", "Website", "Owner or CEO found", "Owner age (estimate)",
               "Leader since")


def clear_rebuildable(conn, client: str) -> None:
    """Remove what eta-us rebuilds from local files (sieve 1, PPP/Form 5500 claims, plan signers) and keep what
    sieve 2 and the paid owner lookup produced. Companies with neither are removed and re-added if still kept."""
    like = " AND ".join("claim NOT LIKE ?" for _ in KEEP_CLAIMS)
    conn.execute(f"DELETE FROM eta_evidence WHERE client=? AND company_number LIKE 'US-%' AND {like}",
                 (client, *KEEP_CLAIMS))
    conn.execute("DELETE FROM eta_screen WHERE client=? AND company_number LIKE 'US-%' AND sieve=1", (client,))
    conn.execute("DELETE FROM eta_owners WHERE client=? AND company_number LIKE 'US-%' AND person_key LIKE 'form5500:%'",
                 (client,))
    conn.execute("DELETE FROM eta_companies WHERE client=? AND company_number LIKE 'US-%' AND company_number NOT IN"
                 " (SELECT company_number FROM eta_screen WHERE client=? AND sieve=2) AND company_number NOT IN"
                 " (SELECT company_number FROM eta_owners WHERE client=?)", (client, client, client))


def run(conn, client: str, eta: dict, ppp_path: Path | None, employers: dict | None = None,
        limit: int | None = None) -> dict:
    """Screen every candidate; store the survivors (pass and review), best first, up to the cap.
    Failed candidates are only counted."""
    us = eta.get("us") or {}
    sieve, band = us.get("sieve1") or {}, float(us.get("revenue_band", 0.3))
    labels = {str(k): v for k, v in (us.get("naics_codes") or {}).items()}
    borrowers = list(stream(ppp_path, us)) if ppp_path and ppp_path.exists() else []
    cands = combine(employers or {}, borrowers, us)
    out = {"candidates": len(cands), "form5500": len(employers or {}), "ppp": len(borrowers),
           "both": sum(1 for c in cands if len(c.sources) == 2), "kept": 0, "new": 0,
           "pass": 0, "review": 0, "fail": 0, "fails": {}}
    scored = []
    for c in cands:
        verdict, score, fails, breakdown = evaluate(c, sieve)
        out[verdict] += 1
        for f in fails:
            out["fails"][f] = out["fails"].get(f, 0) + 1
        if verdict != "fail":
            scored.append((score, c, verdict, fails, breakdown))
    scored.sort(key=lambda x: (-x[0], -x[1].revenue_est))
    for score, c, verdict, fails, breakdown in scored[: limit or us.get("max_per_run", 3000)]:
        out["kept"] += 1
        status = store.upsert_company(conn, client, {
            "company_number": c.company_id, "name": c.name, "company_status": "active",
            "company_type": c.borrower.business_type if c.borrower else None,
            "incorporated": str(c.employer.plan_since) if c.employer and c.employer.plan_since else None,
            "sic_codes": [c.naics], "search_code": c.naics, "locality": f"{c.city}, {c.state}",
            "postal_code": c.zip5, "region": c.state, "stage": "screened",
            "source": "+".join(c.sources)})
        out["new"] += status == "new"
        metrics = c.metrics() | {"industry": labels.get(c.naics)}
        store.save_screen(conn, client, c.company_id, 1, verdict, score, fails, breakdown, metrics)
        ledger(conn, client, c, band)
        if c.employer:
            save_signer(conn, client, c.company_id, c.employer)
        if out["kept"] % 500 == 0:
            conn.commit()
    conn.commit()
    return out
