"""Read UK filed accounts in inline XBRL (iXBRL) into a few numbers per period.

Companies House publishes every electronically filed set of accounts as iXBRL: an XHTML page whose
numbers are tagged with taxonomy concepts (FRS 102 / FRS 105 "core", the older UK GAAP taxonomy, or
IFRS). This module keeps only the facts the ETA screen needs, maps the different concept names to one
canonical metric each, and groups them by period end date. A filing normally carries two periods (this
year and the comparative year), so one document gives two years of history.

Pure Python: no network, no AI. Works on the raw bytes of the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

# canonical metric -> concept local names, in order of preference
CONCEPTS: dict[str, tuple[str, ...]] = {
    "turnover": ("TurnoverRevenue", "TurnoverGrossOperatingRevenue", "Revenue",
                 "RevenueFromContractsWithCustomers"),
    "gross_profit": ("GrossProfitLoss", "GrossProfit"),
    "operating_profit": ("OperatingProfitLoss", "ProfitLossFromOperatingActivities"),
    "profit_before_tax": ("ProfitLossOnOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax"),
    "profit_after_tax": ("ProfitLoss", "ProfitLossForPeriod", "ProfitLossOnOrdinaryActivitiesAfterTax"),
    "employees": ("AverageNumberEmployeesDuringPeriod", "EmployeesTotal"),
    "net_assets": ("NetAssetsLiabilities", "NetAssetsLiabilitiesIncludingPensionAssetLiability",
                   "ShareholderFunds", "Equity", "TotalEquity"),
    "cash": ("CashBankOnHand", "CashBankInHand", "CashCashEquivalents", "CashAndCashEquivalents"),
    "current_assets": ("CurrentAssets",),
    "fixed_assets": ("FixedAssets", "PropertyPlantEquipment", "TangibleFixedAssets"),
    "creditors_within_one_year": ("CreditorsDueWithinOneYear",),
    "creditors_after_one_year": ("CreditorsDueAfterOneYear",),
    "bank_loans": ("BankBorrowings", "BankBorrowingsOverdrafts", "BankLoansOverdrafts", "BankOverdrafts"),
    "retained_earnings": ("RetainedEarningsAccumulatedLosses", "ProfitLossAccountReserve"),
    "depreciation": ("DepreciationExpensePropertyPlantEquipment", "DepreciationAmortisationExpense",
                     "IncreaseFromDepreciationChargeForYearPropertyPlantEquipment"),
    "dividends": ("DividendsPaid", "DividendsPaidOnShares", "EquityDividendsPaid"),
}
_LOOKUP = {name: (metric, rank) for metric, names in CONCEPTS.items() for rank, name in enumerate(names)}

# Creditors are often one concept split by a maturity (or current/non-current) dimension instead of two concepts.
_MATURITY = {"withinoneyear": "creditors_within_one_year", "afteroneyear": "creditors_after_one_year",
             "currentfinancialinstruments": "creditors_within_one_year",
             "non-currentfinancialinstruments": "creditors_after_one_year"}
# Filed FRS 102 accounts tag the profit and loss reserve as Equity on the retained-earnings equity class.
_EQUITY_CLASS = {"retainedearningsaccumulatedlosses": "retained_earnings"}


@dataclass
class Fact:
    metric: str
    concept: str
    period_end: str
    value: float
    context: str


@dataclass
class Accounts:
    periods: dict[str, dict[str, float]] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    company_number: str | None = None
    company_name: str | None = None

    @property
    def latest_period(self) -> str | None:
        return max(self.periods) if self.periods else None

    def value(self, metric: str, period: str | None = None) -> float | None:
        period = period or self.latest_period
        return self.periods.get(period, {}).get(metric) if period else None


def _local(name: str | None) -> str:
    return (name or "").split(":")[-1]


def _tag_is(tag, local: str) -> bool:
    return bool(tag.name) and _local(tag.name).lower() == local.lower()


def _contexts(soup) -> dict[str, dict]:
    out = {}
    for ctx in soup.find_all(lambda t: _tag_is(t, "context")):
        cid = ctx.get("id")
        if not cid:
            continue
        end = None
        for name in ("instant", "enddate"):
            node = ctx.find(lambda t, n=name: _tag_is(t, n))
            if node and node.get_text(strip=True):
                end = node.get_text(strip=True)[:10]
                break
        dims = {}
        for member in ctx.find_all(lambda t: _tag_is(t, "explicitmember")):
            dims[_local(member.get("dimension"))] = _local(member.get_text(strip=True))
        for member in ctx.find_all(lambda t: _tag_is(t, "typedmember")):
            dims[_local(member.get("dimension"))] = member.get_text(strip=True)
        out[cid] = {"end": end, "dims": dims}
    return out


_ZERO_TEXT = {"-", "–", "—", "nil", "none", ""}


def parse_number(text: str, fmt: str | None = None, scale: str | None = None, sign: str | None = None) -> float | None:
    """Value of one ix:nonFraction, following its format, scale and sign attributes."""
    raw = (text or "").strip()
    fmt = _local(fmt).lower()
    if "zerodash" in fmt or "fixedzero" in fmt.replace("-", "") or raw.lower() in _ZERO_TEXT:
        number = 0.0
    else:
        negative = raw.startswith("(") and raw.endswith(")")
        digits = raw.strip("()").replace(" ", "").replace(" ", "")
        if "commadecimal" in fmt.replace("-", ""):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
        digits = re.sub(r"[^0-9.\-]", "", digits)
        if not digits or digits in {"-", "."}:
            return None
        try:
            number = float(digits)
        except ValueError:
            return None
        if negative:
            number = -abs(number)
    if scale:
        try:
            number *= 10 ** int(scale)
        except ValueError:
            pass
    if (sign or "").strip() == "-":
        number = -number
    return number


def parse(content: bytes | str) -> Accounts:
    soup = BeautifulSoup(content, "html.parser")
    contexts = _contexts(soup)
    best: dict[tuple[str, str], tuple[int, Fact]] = {}
    for node in soup.find_all(lambda t: _tag_is(t, "nonfraction")):
        concept = _local(node.get("name"))
        ctx = contexts.get(node.get("contextref") or "")
        if not ctx or not ctx["end"]:
            continue
        metric, rank = _LOOKUP.get(concept, (None, 99))
        dims = ctx["dims"]
        if concept == "Creditors" and dims:
            if len(dims) != 1:
                continue
            metric, rank = _MATURITY.get(next(iter(dims.values())).lower()), 0
        elif concept == "Equity" and dims:
            if len(dims) != 1:
                continue
            metric, rank = _EQUITY_CLASS.get(next(iter(dims.values())).lower()), 1
        elif dims:
            continue   # dimensioned facts are breakdowns (by class of equity, by asset type, ...)
        if not metric:
            continue
        value = parse_number(node.get_text(), node.get("format"), node.get("scale"), node.get("sign"))
        if value is None:
            continue
        key = (ctx["end"], metric)
        fact = Fact(metric=metric, concept=concept, period_end=ctx["end"], value=value, context=node.get("contextref"))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, fact)

    acc = Accounts()
    for (period, metric), (_, fact) in sorted(best.items()):
        acc.periods.setdefault(period, {})[metric] = fact.value
        acc.facts.append(fact)
    for node in soup.find_all(lambda t: _tag_is(t, "nonnumeric")):
        concept = _local(node.get("name"))
        if concept == "UKCompaniesHouseRegisteredNumber" and not acc.company_number:
            acc.company_number = node.get_text(strip=True)
        elif concept == "EntityCurrentLegalOrRegisteredName" and not acc.company_name:
            acc.company_name = node.get_text(" ", strip=True)
    return acc
