"""Read what the register says about each found company: profile, filed accounts and owners.

Three steps, each moving companies one stage on, so a run can stop anywhere and the next run resumes:

    found      -> profile  -> profiled    (or dropped: insolvency, overdue or stale accounts, wrong accounts type)
    profiled   -> accounts -> accounts_read  (numbers from the latest two filed iXBRL accounts, when filed online)
    accounts_read -> owners -> owners_read  (persons with significant control and directors)

Every number and owner row keeps the register URL it came from. Filed documents are cached in
data/eta/docs/ so a re-run never downloads the same filing twice.
"""

from __future__ import annotations

import re
from datetime import date

from gtm import ixbrl
from gtm.config import data_dir
from gtm.eta import store

SOURCE_PROFILE = "companies_house:profile"


def years_between(start: str | None, today: date | None = None) -> float | None:
    if not start:
        return None
    today = today or date.today()
    y, m, d = (int(x) for x in start[:10].split("-"))
    return round((today - date(y, m, d)).days / 365.25, 1)


def months_since(day: str | None, today: date | None = None) -> float | None:
    years = years_between(day, today)
    return None if years is None else round(years * 12, 1)


# ---------- profile ----------

def profile_drop_reason(profile: dict, hard: dict, today: date | None = None) -> str | None:
    if hard.get("exclude_insolvency_history", True) and profile.get("has_insolvency_history"):
        return "insolvency_history"
    accounts = profile.get("accounts") or {}
    if hard.get("exclude_overdue_accounts", True) and accounts.get("overdue"):
        return "accounts_overdue"
    last = accounts.get("last_accounts") or {}
    allowed = hard.get("accounts_types_allowed")
    if allowed and last.get("type") not in allowed:
        return f"accounts_type_{last.get('type') or 'none'}"
    max_age = hard.get("max_accounts_age_months")
    age = months_since(last.get("made_up_to"), today)
    if max_age and (age is None or age > max_age):
        return "accounts_stale"
    years = years_between(profile.get("date_of_creation"), today)
    if hard.get("min_years") and years is not None and years < hard["min_years"]:
        return "too_young"
    return None


def profile_step(ch, conn, client: str, eta: dict, limit: int | None = None, today: date | None = None) -> dict:
    hard = (eta.get("sieve1") or {}).get("hard", {})
    out = {"profiled": 0, "dropped": {}, "missing": 0}
    for row in store.companies_at(conn, client, "found", limit):
        number = row["company_number"]
        profile = ch.profile(number)
        if not profile:
            store.set_stage(conn, client, number, "dropped", "not_on_register")
            out["missing"] += 1
            continue
        last = (profile.get("accounts") or {}).get("last_accounts") or {}
        fields = dict(accounts_type=last.get("type"), accounts_made_up_to=last.get("made_up_to"),
                      accounts_overdue=int(bool((profile.get("accounts") or {}).get("overdue"))),
                      has_charges=int(bool(profile.get("has_charges"))),
                      has_insolvency=int(bool(profile.get("has_insolvency_history"))),
                      company_status=profile.get("company_status"), incorporated=profile.get("date_of_creation"))
        reason = profile_drop_reason(profile, hard, today)
        url = store.register_url(number)
        store.record_evidence(conn, client, number, "Incorporated", profile.get("date_of_creation"), "public", url)
        store.record_evidence(conn, client, number, "Latest accounts", f"{last.get('type')} to {last.get('made_up_to')}",
                              "public", url + "/filing-history")
        if reason:
            store.set_stage(conn, client, number, "dropped", reason, **fields)
            out["dropped"][reason] = out["dropped"].get(reason, 0) + 1
        else:
            store.set_stage(conn, client, number, "profiled", None, **fields)
            out["profiled"] += 1
        conn.commit()
    return out


# ---------- accounts ----------

def _cache_path(number: str, transaction_id: str):
    path = data_dir() / "eta" / "docs" / number
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{re.sub(r'[^A-Za-z0-9_-]', '_', transaction_id)}.xhtml"


def accounts_step(ch, conn, client: str, eta: dict, limit: int | None = None, filings_per_company: int = 2) -> dict:
    out = {"read": 0, "no_online_accounts": 0, "periods": 0}
    for row in store.companies_at(conn, client, "profiled", limit):
        number = row["company_number"]
        filings = [f for f in ch.accounts_filings(number) if f.get("type") == "AA"
                   and (f.get("links") or {}).get("document_metadata")]
        filings.sort(key=lambda f: f.get("date") or "", reverse=True)
        read_any = False
        for filing in filings[:filings_per_company]:
            meta_url = filing["links"]["document_metadata"]
            tid = filing.get("transaction_id") or meta_url.rsplit("/", 1)[-1]
            cache = _cache_path(number, tid)
            if cache.exists():
                content = cache.read_bytes()
            else:
                formats = (ch.document_formats(meta_url) or {}).get("resources") or {}
                if "application/xhtml+xml" not in formats:
                    continue          # filed on paper or as PDF only: no tagged numbers
                content = ch.document_content(meta_url)
                cache.write_bytes(content)
            parsed = ixbrl.parse(content)
            if parsed.company_number and parsed.company_number.lstrip("0") != number.lstrip("0"):
                continue              # never trust a document that names another company
            source = store.register_url(number) + f"/filing-history/{tid}"
            for fact in parsed.facts:
                store.save_financial(conn, client, number, fact.period_end, fact.metric, fact.value,
                                     fact.concept, source, filing.get("date"))
                out["periods"] += 1
            read_any = read_any or bool(parsed.facts)
        if read_any:
            out["read"] += 1
            store.set_stage(conn, client, number, "accounts_read", None)
        else:
            out["no_online_accounts"] += 1
            store.set_stage(conn, client, number, "accounts_read", "no_online_accounts")
        conn.commit()
    return out


# ---------- owners ----------

_BAND = re.compile(r"(\d+)-to-(\d+)-percent")


def ownership_band(natures: list[str]) -> str | None:
    """Highest share band among the natures of control, e.g. 'ownership-of-shares-75-to-100-percent' -> '75-100'."""
    best = None
    for nature in natures or []:
        if not nature.startswith("ownership-of-shares"):
            continue
        m = _BAND.search(nature)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), int(m.group(2)))
    return f"{best[0]}-{best[1]}" if best else None


def _dob(item: dict) -> tuple[int | None, int | None]:
    dob = item.get("date_of_birth") or {}
    return dob.get("year"), dob.get("month")


def owners_step(ch, conn, client: str, eta: dict, limit: int | None = None) -> dict:
    out = {"companies": 0, "pscs": 0, "directors": 0}
    for row in store.companies_at(conn, client, "accounts_read", limit):
        number = row["company_number"]
        base = store.register_url(number)
        for item in ch.pscs(number):
            kind = item.get("kind", "")
            year, month = _dob(item)
            store.save_owner(conn, client, number, {
                "person_key": (item.get("links") or {}).get("self") or f"psc:{item.get('name')}",
                "kind": ("psc_individual" if kind.startswith("individual")
                         else "psc_corporate" if kind.startswith("corporate") else "psc_other"),
                "name": item.get("name"), "role": "person with significant control",
                "birth_year": year, "birth_month": month, "appointed_on": item.get("notified_on"),
                "ceased_on": item.get("ceased_on"), "ownership": ownership_band(item.get("natures_of_control")),
                "source": base + "/persons-with-significant-control",
            })
            out["pscs"] += 1
        for item in ch.officers(number):
            if item.get("officer_role") not in ("director", "corporate-director"):
                continue
            year, month = _dob(item)
            store.save_owner(conn, client, number, {
                "person_key": (item.get("links") or {}).get("self") or f"officer:{item.get('name')}:{item.get('appointed_on')}",
                "kind": "director", "name": item.get("name"), "role": item.get("officer_role"),
                "birth_year": year, "birth_month": month, "appointed_on": item.get("appointed_on"),
                "ceased_on": item.get("resigned_on"), "ownership": None, "source": base + "/officers",
            })
            out["directors"] += 1
        store.set_stage(conn, client, number, "owners_read", row["stage_reason"])
        out["companies"] += 1
        conn.commit()
    return out
