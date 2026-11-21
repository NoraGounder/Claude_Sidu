"""United States: discovery and sieve 1 from the SBA's public Paycheck Protection Program file.

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


# ---------- sieve 1 ----------

def hard_fails(b: Borrower, hard: dict) -> list[str]:
    fails = []
    if b.revenue_est < hard.get("revenue_min_usd", 0):
        fails.append("too_small_revenue_estimate")
    if b.revenue_est > hard.get("revenue_max_usd", 10**12):
        fails.append("too_large_revenue_estimate")
    if b.jobs < hard.get("jobs_min", 0):
        fails.append("too_few_employees")
    if b.jobs > hard.get("jobs_max", 10**9):
        fails.append("too_many_employees")
    if hard.get("exclude_change_of_ownership", True) and "change of ownership" in b.business_age.lower():
        fails.append("recent_change_of_ownership")
    if b.business_age.lower().startswith(("new business", "startup")):
        fails.append("short_history")
    return fails


def components(b: Borrower, bars: dict, weights: dict) -> dict[str, float]:
    lo, hi = bars.get("revenue_target_usd", [10e6, 30e6])
    jlo, jhi = bars.get("jobs_target", [20, 200])
    pay = b.payroll_est / b.jobs if b.jobs else 0
    base = b.first_draw or b.second_draw
    clo, chi = bars.get("revenue_core_usd", [12e6, 25e6])
    size = 1.0 if clo <= b.revenue_est <= chi else 0.7 if lo <= b.revenue_est <= hi else 0.3
    out = {
        "size": size,
        "jobs": 1.0 if jlo <= b.jobs <= jhi else 0.4,
        "skilled_pay": min(pay / bars.get("payroll_per_job_good_usd", 50000), 1.0),
        # a second draw needed a 25% fall in quarterly revenue in 2020
        "resilience": 0.3 if b.second_draw else 1.0,
        "forgiven": 1.0 if base and b.forgiven >= 0.95 * (b.first_draw + b.second_draw) else 0.3,
        "entity": 1.0 if "corporation" in b.business_type.lower() or "llc" in b.business_type.lower() else 0.5,
        "history": 1.0 if b.business_age.lower().startswith("existing") else 0.4,
    }
    return {k: round(v * float(weights.get(k, 0)), 1) for k, v in out.items()}


def evaluate(b: Borrower, sieve: dict) -> tuple[str, float, list[str], dict]:
    fails = hard_fails(b, sieve.get("hard") or {})
    breakdown = components(b, sieve.get("bars") or {}, sieve.get("weights") or {})
    score = round(sum(breakdown.values()), 1)
    if fails:
        return "fail", score, fails, breakdown
    verdict = "pass" if score >= sieve.get("pass", 60) else "review" if score >= sieve.get("review", 40) else "fail"
    return verdict, score, fails, breakdown


def ledger(conn, client: str, b: Borrower, band: float) -> None:
    src = f"{DATASET_URL} (loans {', '.join(x for x in b.loans if x)})"
    put = lambda claim, value, status, step=None: store.record_evidence(conn, client, b.company_id, claim, value,
                                                                         status, src, step)
    put("Jobs reported (PPP, 2020-21)", str(b.jobs), "public")
    put("PPP first-draw loan", f"${b.first_draw:,.0f}", "public")
    if b.second_draw:
        put("PPP second-draw loan", f"${b.second_draw:,.0f} (needed a 25% revenue fall in 2020)", "public")
    put("Annual payroll (estimate)", f"${b.payroll_est:,.0f}", "unverified", "Payroll register or W-3 from the seller")
    put("Revenue (estimate)", f"${b.revenue_est * (1 - band):,.0f} - ${b.revenue_est * (1 + band):,.0f}",
        "unverified", "Three years of tax returns and P&L from the seller")
    put("Business age (PPP)", b.business_age, "public")
    for claim in ("EBITDA", "Owner age", "Owner earnings", "Customer concentration", "Recurring revenue"):
        put(claim, None, "unknown", "Ask the owner or broker")


def run(conn, client: str, eta: dict, path: Path, limit: int | None = None) -> dict:
    """Screen every borrower in the file; store the survivors (pass and review), best first, up to the cap.
    Failed borrowers are only counted: there is no reason to keep them."""
    us = eta.get("us") or {}
    sieve, band = us.get("sieve1") or {}, float(us.get("revenue_band", 0.3))
    labels = {str(k): v for k, v in (us.get("naics_codes") or {}).items()}
    out = {"kept": 0, "new": 0, "pass": 0, "review": 0, "fail": 0, "fails": {}}
    cap = limit or us.get("max_per_run", 2000)
    scored = []
    for b in stream(path, us):
        verdict, score, fails, breakdown = evaluate(b, sieve)
        out[verdict] += 1
        out["screened"] = out.get("screened", 0) + 1
        for f in fails:
            out["fails"][f] = out["fails"].get(f, 0) + 1
        if verdict != "fail":
            scored.append((score, b, verdict, fails, breakdown))
    scored.sort(key=lambda x: (-x[0], -x[1].revenue_est))
    for score, b, verdict, fails, breakdown in scored[:cap]:
        out["kept"] += 1
        status = store.upsert_company(conn, client, {
            "company_number": b.company_id, "name": b.name, "company_status": b.loan_status,
            "company_type": b.business_type, "sic_codes": [b.naics], "search_code": b.naics,
            "locality": f"{b.city}, {b.state}", "postal_code": b.zip5, "region": b.state,
            "stage": "screened", "source": SOURCE})
        out["new"] += status == "new"
        metrics = {k: v for k, v in b.as_dict().items() if k not in ("loans",)}
        metrics["industry"] = labels.get(b.naics)
        store.save_screen(conn, client, b.company_id, 1, verdict, score, fails, breakdown, metrics)
        ledger(conn, client, b, band)
        if out["kept"] % 200 == 0:
            conn.commit()
    conn.commit()
    return out
