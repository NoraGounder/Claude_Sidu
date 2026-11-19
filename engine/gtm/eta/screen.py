"""Sieve 1: screen each company on public numbers only (eta.yaml `sieve1`).

Hard checks drop a company (too young, insolvent, owned by a group, negative equity, out of the size
band). Everything else is scored, never a reason to drop on its own: the board's rule is that bars
trigger review, not rejection. Each check also writes a line in the evidence ledger: the value with
status `public` when the register shows it, or `unknown` with the question or document request that would
settle it in the owner conversation (sieve 3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from gtm.eta import store
from gtm.eta.enrich import months_since, years_between

UNKNOWN_STEPS = {
    "Turnover": "Ask for three years of profit and loss accounts",
    "Operating margin": "Ask for three years of profit and loss accounts",
    "Employees": "Ask for the headcount and organisation chart",
    "Majority owner age": "Confirm who owns the shares and their plans",
    "Owner earnings": "Needs P&L, maintenance capex and working capital from the owner (sieve 3)",
    "Customer concentration": "Request revenue by customer for three years (sieve 3)",
}


@dataclass
class Metrics:
    years: float | None = None
    accounts_age_months: float | None = None
    period: str | None = None
    turnover: float | None = None
    operating_profit: float | None = None
    operating_margin: float | None = None
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
        if m.turnover and m.operating_profit is not None and m.turnover > 0:
            m.operating_margin = round(m.operating_profit / m.turnover, 4)
        m.net_assets = latest.get("net_assets")
        m.cash = latest.get("cash")
        debt_parts = [latest.get("creditors_after_one_year"), latest.get("bank_loans")]
        if any(v is not None for v in debt_parts):
            # Bank loans are usually inside creditors; use the larger figure rather than adding twice.
            m.debt = max(abs(v) for v in debt_parts if v is not None)
            m.net_debt = m.debt - (m.cash or 0)
        m.employees = next((fin[p]["employees"] for p in reversed(periods) if "employees" in fin[p]), None)
        if len(periods) >= 2:
            m.net_assets_prior = fin[periods[-2]].get("net_assets")
        retained = [fin[p]["retained_earnings"] for p in periods if "retained_earnings" in fin[p]][-4:]
        m.retained_periods = len(retained)
        if len(retained) >= 2:
            m.retained_growth_years = sum(1 for a, b in zip(retained, retained[1:]) if b > a)

    individuals, ages = [], []
    for o in store.owners(conn, client, row["company_number"]):
        if o["ceased_on"]:
            continue
        if o["kind"] == "psc_corporate" and _majority(o["ownership"]):
            m.corporate_majority = True
        if o["kind"] == "psc_individual":
            individuals.append(o)
        if o["kind"] == "director":
            m.directors += 1
            if o["birth_year"]:
                age = today.year - o["birth_year"]
                ages.append(age)
                if age < 55:
                    m.directors_under_55 += 1
    owner = sorted(individuals, key=lambda o: int((o["ownership"] or "0-0").split("-")[0]), reverse=True)
    if owner and owner[0]["birth_year"]:
        m.owner_age = today.year - owner[0]["birth_year"]
        m.owner_band = owner[0]["ownership"]
    return m


def hard_fails(row, m: Metrics, hard: dict) -> list[str]:
    fails = []
    if hard.get("min_years") and m.years is not None and m.years < hard["min_years"]:
        fails.append("younger_than_min_years")
    allowed = hard.get("accounts_types_allowed")
    if allowed and row["accounts_type"] not in allowed:
        fails.append("accounts_type")
    if hard.get("exclude_insolvency_history", True) and row["has_insolvency"]:
        fails.append("insolvency_history")
    if hard.get("exclude_overdue_accounts", True) and row["accounts_overdue"]:
        fails.append("accounts_overdue")
    if hard.get("exclude_corporate_majority_owner", True) and m.corporate_majority:
        fails.append("owned_by_a_company")
    if hard.get("max_accounts_age_months") and (m.accounts_age_months is None
                                                or m.accounts_age_months > hard["max_accounts_age_months"]):
        fails.append("accounts_stale")
    if m.net_assets is not None and m.net_assets < hard.get("min_net_assets_gbp", 1):
        fails.append("negative_equity")
    if m.employees is not None:
        if m.employees < hard.get("employees_min", 0):
            fails.append("too_few_employees")
        if hard.get("employees_max") and m.employees > hard["employees_max"]:
            fails.append("too_many_employees")
    if m.turnover is not None:
        if m.turnover < hard.get("turnover_min_gbp", 0):
            fails.append("turnover_below_band")
        if hard.get("turnover_max_gbp") and m.turnover > hard["turnover_max_gbp"]:
            fails.append("turnover_above_band")
    return fails


def components(m: Metrics, bars: dict, hard: dict) -> dict[str, float]:
    """Each component from 0 to 1, before weighting."""
    margin_bar = bars.get("operating_margin_min", 0.10)
    if m.operating_margin is not None:
        profit = 1.0 if m.operating_margin >= margin_bar else max(m.operating_margin, 0) / margin_bar * 0.7
    elif m.retained_growth_years is not None:
        needed = bars.get("retained_earnings_growth_years", 2)
        # A proxy is less certain than a filed margin, so it tops out at 0.8.
        profit = 0.8 if m.retained_growth_years >= needed else 0.4 if m.retained_growth_years >= 1 else 0.0
    else:
        profit = 0.2

    if m.net_assets is None:
        balance = 0.2
    else:
        balance = 0.5 if m.net_assets > 0 else 0.0
        if m.net_assets > 0:
            ratio = (m.net_debt or 0) / m.net_assets
            if ratio <= bars.get("net_debt_to_net_assets_max", 1.0):
                balance += 0.3
            if m.net_assets_prior is not None and m.net_assets > m.net_assets_prior:
                balance += 0.2

    size = 0.0
    if m.employees is None:
        size += 0.3
    elif hard.get("employees_min", 0) <= m.employees <= hard.get("employees_max", 10**9):
        size += 0.6
    if m.turnover is None:
        size += 0.2
    elif hard.get("turnover_min_gbp", 0) <= m.turnover <= hard.get("turnover_max_gbp", 10**12):
        size += 0.4

    if m.owner_age is None:
        succession = 0.3
    elif m.owner_age >= bars.get("owner_age_succession", 60):
        succession = 1.0
    elif m.owner_age >= bars.get("owner_age_watch", 55):
        succession = 0.6
    else:
        succession = 0.1

    history = 0.0 if m.years is None else 1.0 if m.years >= 20 else 0.6 if m.years >= 10 else 0.2
    disclosure = 1.0 if m.turnover is not None else 0.4
    return {"profit_evidence": profit, "balance_sheet": min(balance, 1.0), "size_fit": min(size, 1.0),
            "succession": succession, "history": history, "disclosure": disclosure}


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
    put("Operating margin", None if m.operating_margin is None else f"{m.operating_margin:.1%}", filings)
    put("Net assets", _money(m.net_assets), filings)
    put("Cash", _money(m.cash), filings)
    put("Debt (bank and long-term creditors)", _money(m.debt), filings)
    put("Employees", None if m.employees is None else int(m.employees), filings)
    if m.retained_growth_years is not None:
        put("Retained earnings grew", f"{m.retained_growth_years} of last {m.retained_periods - 1} years", filings)
    put("Majority owner age", None if m.owner_age is None else f"about {m.owner_age} ({m.owner_band}% of shares)",
        owners_url)
    store.record_evidence(conn, client, number, "Owner earnings", None, "unknown", None, UNKNOWN_STEPS["Owner earnings"])
    store.record_evidence(conn, client, number, "Customer concentration", None, "unknown", None,
                          UNKNOWN_STEPS["Customer concentration"])


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
