"""Sieve 1: the Stanford Search Fund company criteria, checked on public numbers only (eta.yaml `sieve1`).

Source: Stanford GSB, "2026 A Primer on Search Funds", Part IV. The Primer's *undesirable* company traits
that the register can prove are hard fails (turnaround: losses, negative equity or insolvency; too small:
under $10M revenue or $1.5M EBITDA; owned by a group, so no motivated owner-seller). Its *desirable* traits
are scored 0-100: financial size, EBITDA margin above 15%, return on tangible capital above 20%, a history of
cash generation, a motivated seller (owner near retirement) and solid management below the owner.

Unknowns never fail a company. Each check writes a line in the evidence ledger: the value with status
`public` when the register shows it, or `unknown` with the question that settles it in the owner conversation.
Industry criteria and competitive advantage (Hamilton Helmer's 7 Powers) are sieve 2 (gtm/eta/qualify.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from gtm.eta import store
from gtm.eta.enrich import months_since, years_between

UNKNOWN_STEPS = {
    "Turnover": "Ask for three years of profit and loss accounts",
    "EBITDA": "Ask for three years of profit and loss accounts and the depreciation note",
    "EBITDA margin": "Ask for three years of profit and loss accounts",
    "Return on tangible capital": "Needs operating profit from the P&L",
    "Employees": "Ask for the headcount and organisation chart",
    "Majority owner age": "Confirm who owns the shares and their plans",
    "Owner earnings": "Needs P&L, maintenance capex and working capital from the owner (sieve 3)",
    "Customer concentration": "Request revenue by customer for three years (Stanford: none above 30%)",
    "Recurring revenue": "Ask what share of revenue repeats under contracts or regular orders (sieve 3)",
}


@dataclass
class Metrics:
    years: float | None = None
    accounts_age_months: float | None = None
    period: str | None = None
    turnover: float | None = None
    operating_profit: float | None = None
    depreciation: float | None = None
    ebitda: float | None = None
    ebitda_margin: float | None = None
    rotc: float | None = None
    net_assets: float | None = None
    net_assets_prior: float | None = None
    cash: float | None = None
    debt: float | None = None
    net_debt: float | None = None
    employees: float | None = None
    retained_growth_years: int | None = None
    retained_periods: int = 0
    owner_age: int | None = None
    owner_band: str | None = None
    corporate_majority: bool = False
    directors: int = 0
    directors_under_55: int = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Result:
    verdict: str
    score: float
    hard_fails: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    metrics: Metrics = field(default_factory=Metrics)


def _majority(band: str | None) -> bool:
    return bool(band) and int(band.split("-")[0]) >= 50


def gather(conn, client: str, row, today: date | None = None) -> Metrics:
    today = today or date.today()
    m = Metrics(years=years_between(row["incorporated"], today),
                accounts_age_months=months_since(row["accounts_made_up_to"], today))
    fin = store.financials(conn, client, row["company_number"])
    periods = sorted(fin)
    if periods:
        latest = fin[periods[-1]]
        m.period = periods[-1]
        m.turnover = latest.get("turnover")
        m.operating_profit = latest.get("operating_profit")
        m.depreciation = latest.get("depreciation")
        if m.operating_profit is not None:
            # EBITDA = operating profit + depreciation. Without the depreciation note, operating profit is the
            # conservative floor (it understates EBITDA, never overstates it).
            m.ebitda = m.operating_profit + abs(m.depreciation or 0)
        if m.turnover and m.ebitda is not None and m.turnover > 0:
            m.ebitda_margin = round(m.ebitda / m.turnover, 4)
        m.net_assets = latest.get("net_assets")
        m.cash = latest.get("cash")
        debt_parts = [latest.get("creditors_after_one_year"), latest.get("bank_loans")]
        if any(v is not None for v in debt_parts):
            # Bank loans are usually inside creditors; use the larger figure rather than adding twice.
            m.debt = max(abs(v) for v in debt_parts if v is not None)
            m.net_debt = m.debt - (m.cash or 0)
        if m.operating_profit is not None and m.net_assets and m.net_assets > 0:
            # Return on tangible capital, approximated by return on capital employed: equity plus net debt.
            capital = m.net_assets + max(m.net_debt or 0, 0)
            m.rotc = round(m.operating_profit / capital, 4) if capital > 0 else None
        m.employees = next((fin[p]["employees"] for p in reversed(periods) if "employees" in fin[p]), None)
        if len(periods) >= 2:
            m.net_assets_prior = fin[periods[-2]].get("net_assets")
        retained = [fin[p]["retained_earnings"] for p in periods if "retained_earnings" in fin[p]][-4:]
        m.retained_periods = len(retained)
        if len(retained) >= 2:
            m.retained_growth_years = sum(1 for a, b in zip(retained, retained[1:]) if b > a)

    individuals = []
    for o in store.owners(conn, client, row["company_number"]):
        if o["ceased_on"]:
            continue
        if o["kind"] == "psc_corporate" and _majority(o["ownership"]):
            m.corporate_majority = True
        if o["kind"] == "psc_individual":
            individuals.append(o)
        if o["kind"] == "director":
            m.directors += 1
            if o["birth_year"] and today.year - o["birth_year"] < 55:
                m.directors_under_55 += 1
    owner = sorted(individuals, key=lambda o: int((o["ownership"] or "0-0").split("-")[0]), reverse=True)
    if owner and owner[0]["birth_year"]:
        m.owner_age = today.year - owner[0]["birth_year"]
        m.owner_band = owner[0]["ownership"]
    return m


def hard_fails(row, m: Metrics, hard: dict) -> list[str]:
    """Stanford's undesirable company traits, where the register proves them. Unknown never fails."""
    fails = []
    if hard.get("min_years") and m.years is not None and m.years < hard["min_years"]:
        fails.append("short_history")
    allowed = hard.get("accounts_types_allowed")
    if allowed and row["accounts_type"] not in allowed:
        fails.append("accounts_type")
    if hard.get("exclude_insolvency_history", True) and row["has_insolvency"]:
        fails.append("turnaround_insolvency_history")
    if hard.get("exclude_overdue_accounts", True) and row["accounts_overdue"]:
        fails.append("accounts_overdue")
    if hard.get("exclude_corporate_majority_owner", True) and m.corporate_majority:
        fails.append("no_motivated_owner_group_owned")
    if hard.get("max_accounts_age_months") and (m.accounts_age_months is None
                                                or m.accounts_age_months > hard["max_accounts_age_months"]):
        fails.append("accounts_stale")
    if m.net_assets is not None and m.net_assets < hard.get("min_net_assets_gbp", 1):
        fails.append("turnaround_negative_equity")
    if hard.get("exclude_loss_making", True) and m.operating_profit is not None and m.operating_profit < 0:
        fails.append("turnaround_operating_loss")
    if m.turnover is not None:
        if m.turnover < hard.get("turnover_min_gbp", 0):
            fails.append("too_small_revenue")
        if hard.get("turnover_max_gbp") and m.turnover > hard["turnover_max_gbp"]:
            fails.append("too_large_revenue")
    if m.ebitda is not None and m.ebitda < hard.get("ebitda_min_gbp", 0):
        fails.append("too_small_ebitda")
    if m.employees is not None:
        if m.employees < hard.get("employees_min", 0):
            fails.append("too_few_employees")
        if hard.get("employees_max") and m.employees > hard["employees_max"]:
            fails.append("too_many_employees")
    return fails


def _in(value: float | None, band: list | None) -> bool:
    return value is not None and bool(band) and band[0] <= value <= band[1]


def components(m: Metrics, bars: dict, hard: dict) -> dict[str, float]:
    """Each Stanford criterion from 0 to 1, before weighting. Unknown sits low but above zero."""
    size = 0.0
    size += 0.5 if _in(m.turnover, bars.get("turnover_target_gbp")) else 0.15 if m.turnover is None else 0.0
    size += 0.5 if _in(m.ebitda, bars.get("ebitda_target_gbp")) else 0.15 if m.ebitda is None else 0.0

    target, floor = bars.get("ebitda_margin_target", 0.15), bars.get("ebitda_margin_floor", 0.10)
    if m.ebitda_margin is not None:
        profit = 1.0 if m.ebitda_margin >= target else 0.5 if m.ebitda_margin >= floor else 0.0
    elif m.retained_growth_years is not None:
        needed = bars.get("retained_earnings_growth_years", 2)
        profit = 0.6 if m.retained_growth_years >= needed else 0.3 if m.retained_growth_years >= 1 else 0.0
    else:
        profit = 0.2

    rotc_target = bars.get("rotc_target", 0.20)
    roc = 0.2 if m.rotc is None else 1.0 if m.rotc >= rotc_target else max(m.rotc, 0) / rotc_target * 0.6

    cash = 0.0 if m.years is None else 0.5 if m.years >= 20 else 0.3 if m.years >= 10 else 0.0
    if m.net_assets_prior is not None and m.net_assets is not None and m.net_assets > m.net_assets_prior:
        cash += 0.5
    elif m.retained_growth_years:
        cash += 0.3

    if m.owner_age is None:
        seller = 0.3
    elif m.owner_age >= bars.get("owner_age_motivated", 60):
        seller = 1.0
    elif m.owner_age >= bars.get("owner_age_watch", 55):
        seller = 0.6
    else:
        seller = 0.1

    if m.directors == 0:
        bench = 0.3
    elif m.directors_under_55 >= bars.get("bench_directors_under_55", 1):
        bench = 1.0
    elif m.directors >= 2:
        bench = 0.5
    else:
        bench = 0.1      # the owner alone runs it: Stanford "limited or no management bench strength"

    if m.net_assets is None:
        balance = 0.2
    elif m.net_assets <= 0:
        balance = 0.0
    else:
        balance = 1.0 if (m.net_debt or 0) / m.net_assets <= bars.get("net_debt_to_net_assets_max", 1.0) else 0.3

    return {"financial_size": min(size, 1.0), "profitability": profit, "return_on_capital": roc,
            "cash_history": min(cash, 1.0), "motivated_seller": seller, "management_bench": bench,
            "balance_sheet": balance}


def evaluate(row, m: Metrics, sieve: dict) -> Result:
    hard, bars, weights = sieve.get("hard", {}), sieve.get("bars", {}), sieve.get("weights", {})
    parts = components(m, bars, hard)
    breakdown = {k: round(parts[k] * weights.get(k, 0), 1) for k in parts}
    score = round(sum(breakdown.values()), 1)
    fails = hard_fails(row, m, hard)
    if fails:
        verdict = "fail"
    elif score >= sieve.get("pass_score", 60):
        verdict = "pass"
    elif score >= sieve.get("review_score", 40):
        verdict = "review"
    else:
        verdict = "fail"
    return Result(verdict=verdict, score=score, hard_fails=fails, breakdown=breakdown, metrics=m)


def _money(v: float | None) -> str | None:
    return None if v is None else f"£{v:,.0f}"


def _pct(v: float | None) -> str | None:
    return None if v is None else f"{v:.1%}"


def ledger(conn, client: str, row, m: Metrics) -> None:
    number = row["company_number"]
    filings = store.register_url(number) + "/filing-history"
    owners_url = store.register_url(number) + "/persons-with-significant-control"

    def put(claim, value, source):
        if value is None:
            store.record_evidence(conn, client, number, claim, None, "unknown", None, UNKNOWN_STEPS.get(claim))
        else:
            store.record_evidence(conn, client, number, claim, value, "public", source)

    put("Turnover", _money(m.turnover), filings)
    ebitda = _money(m.ebitda)
    if ebitda and m.depreciation is None:
        ebitda += " (operating profit; depreciation not filed)"
    put("EBITDA", ebitda, filings)
    put("EBITDA margin", _pct(m.ebitda_margin), filings)
    put("Return on tangible capital", None if m.rotc is None else f"{m.rotc:.1%} (return on capital employed)", filings)
    put("Net assets", _money(m.net_assets), filings)
    put("Cash", _money(m.cash), filings)
    put("Debt (bank and long-term creditors)", _money(m.debt), filings)
    put("Employees", None if m.employees is None else int(m.employees), filings)
    if m.retained_growth_years is not None:
        put("Retained earnings grew", f"{m.retained_growth_years} of last {m.retained_periods - 1} years", filings)
    put("Majority owner age", None if m.owner_age is None else f"about {m.owner_age} ({m.owner_band}% of shares)",
        owners_url)
    put("Directors under 55", f"{m.directors_under_55} of {m.directors}" if m.directors else None,
        store.register_url(number) + "/officers")
    for claim in ("Owner earnings", "Customer concentration", "Recurring revenue"):
        store.record_evidence(conn, client, number, claim, None, "unknown", None, UNKNOWN_STEPS[claim])


def run(conn, client: str, eta: dict, rescreen: bool = False, today: date | None = None) -> dict:
    sieve = eta.get("sieve1") or {}
    stages = ("owners_read", "screened") if rescreen else ("owners_read",)
    rows = [r for s in stages for r in store.companies_at(conn, client, s)]
    out = {"pass": 0, "review": 0, "fail": 0}
    for row in rows:
        m = gather(conn, client, row, today)
        result = evaluate(row, m, sieve)
        store.save_screen(conn, client, row["company_number"], 1, result.verdict, result.score,
                          result.hard_fails, result.breakdown, m.as_dict())
        ledger(conn, client, row, m)
        store.set_stage(conn, client, row["company_number"], "screened", row["stage_reason"])
        out[result.verdict] += 1
        conn.commit()
    return out


def ranked(conn, client: str, verdicts: tuple[str, ...] = ("pass", "review")) -> list[dict]:
    marks = ",".join("?" for _ in verdicts)
    rows = conn.execute(
        f"SELECT c.*, s.verdict, s.score, s.hard_fails, s.breakdown, s.metrics FROM eta_companies c"
        f" JOIN eta_screen s ON s.client=c.client AND s.company_number=c.company_number AND s.sieve=1"
        f" WHERE c.client=? AND s.verdict IN ({marks}) ORDER BY s.score DESC, c.company_number",
        (client, *verdicts)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["metrics"] = json.loads(d["metrics"])
        d["hard_fails"] = json.loads(d["hard_fails"])
        d["breakdown"] = json.loads(d["breakdown"])
        out.append(d)
    return out
