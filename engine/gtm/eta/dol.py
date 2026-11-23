"""United States: current size and age from the Department of Labor's Form 5500 filings (free, public).

Every US employer with a retirement or welfare plan files Form 5500 (large plans) or 5500-SF (small plans) each
year. The DOL publishes all of them as CSV (askebsa.dol.gov, "FOIA Files"). For the ETA search each filing gives:

    employer name, EIN, city, state, ZIP, NAICS business code   -> who and where
    active participants at year end                              -> current headcount (best free measure)
    plan effective date                                          -> the company is at least this old
    the same employer in an earlier year                         -> headcount growth
    final filing flag                                            -> plan ended (company sold, closed or merged)
    the name of the person who signed for the employer           -> often the owner or president (data/ only)

Files are cached in data/eta/dol/ (about 750 MB a year, unzipped). Nothing here calls a paid service.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

from gtm.config import data_dir

BASE = "https://askebsa.dol.gov/FOIA%20Files/{year}/Latest/{name}.zip"
SOURCE_PAGE = "https://www.dol.gov/agencies/ebsa/about-ebsa/our-activities/public-disclosure/foia/form-5500-datasets"
FILES = {"sf": "F_5500_SF_{year}_Latest", "large": "F_5500_{year}_Latest"}

# column names per form: (small-plan 5500-SF, large-plan 5500)
COLS = {
    "name": ("SF_SPONSOR_NAME", "SPONSOR_DFE_NAME"),
    "dba": ("SF_SPONSOR_DFE_DBA_NAME", "SPONS_DFE_DBA_NAME"),
    "ein": ("SF_SPONS_EIN", "SPONS_DFE_EIN"),
    "city": ("SF_SPONS_US_CITY", "SPONS_DFE_MAIL_US_CITY"),
    "state": ("SF_SPONS_US_STATE", "SPONS_DFE_MAIL_US_STATE"),
    "zip": ("SF_SPONS_US_ZIP", "SPONS_DFE_MAIL_US_ZIP"),
    "naics": ("SF_BUSINESS_CODE", "BUSINESS_CODE"),
    "active": ("SF_TOT_ACT_PARTCP_EOY_CNT", "TOT_ACTIVE_PARTCP_CNT"),
    "effective": ("SF_PLAN_EFF_DATE", "PLAN_EFF_DATE"),
    "final": ("SF_FINAL_FILING_IND", "FINAL_FILING_IND"),
    "signer": ("SF_SPONS_SIGNED_NAME", "SPONS_SIGNED_NAME"),
    "admin_signer": ("SF_ADMIN_SIGNED_NAME", "ADMIN_SIGNED_NAME"),
    "admin_ein": ("SF_ADMIN_EIN", "ADMIN_EIN"),
    "admin_same": ("SF_ADMIN_NAME_SAME_SPON_IND", "ADMIN_NAME_SAME_SPON_IND"),
    "phone": ("SF_SPONS_PHONE_NUM", "SPONS_DFE_PHONE_NUM"),
}


def folder() -> Path:
    path = data_dir() / "eta" / "dol"
    path.mkdir(parents=True, exist_ok=True)
    return path


def csv_path(year: int, form: str) -> Path:
    return folder() / (FILES[form].format(year=year).lower() + ".csv")


def download(year: int, session=None) -> list[Path]:
    """Fetch and unzip both forms for a plan year, once."""
    http = session or requests
    out = []
    for form, name in FILES.items():
        dest = csv_path(year, form)
        if not dest.exists():
            resp = http.get(BASE.format(year=year, name=name.format(year=year)), timeout=600)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                dest.write_bytes(zf.read(member))
        out.append(dest)
    return out


def _int(text) -> int:
    try:
        return int(float(text or 0))
    except ValueError:
        return 0


@dataclass
class Employer:
    ein: str
    name: str
    dba: str
    city: str
    state: str
    zip5: str
    naics: str
    active: int = 0                 # largest active-participant count across the employer's plans
    plan_since: int | None = None   # earliest plan effective year
    final_filing: bool = False      # every plan filed a final return
    plans: int = 0
    signer: str | None = None
    year: int = 0
    active_before: int | None = None   # the same EIN in the comparison year
    years_compared: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("signer")             # personal data: kept only in eta_owners
        return d


def read_year(year: int, codes: set[str] | None = None) -> dict[str, Employer]:
    """All employers in the target NAICS codes for one plan year, keyed by EIN."""
    csv.field_size_limit(10**8)
    out: dict[str, Employer] = {}
    finals: dict[str, list[bool]] = {}
    for idx, form in enumerate(("sf", "large")):
        path = csv_path(year, form)
        if not path.exists():
            continue
        col = {k: v[idx] for k, v in COLS.items()}
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                naics = (row.get(col["naics"]) or "").strip()
                if codes and naics not in codes:
                    continue
                ein = (row.get(col["ein"]) or "").strip()
                if not ein:
                    continue
                e = out.get(ein)
                if e is None:
                    e = out[ein] = Employer(ein=ein, name=(row.get(col["name"]) or "").strip(),
                                            dba=(row.get(col["dba"]) or "").strip(),
                                            city=(row.get(col["city"]) or "").strip(),
                                            state=(row.get(col["state"]) or "").strip(),
                                            zip5=(row.get(col["zip"]) or "")[:5], naics=naics, year=year)
                e.plans += 1
                e.active = max(e.active, _int(row.get(col["active"])))
                eff = (row.get(col["effective"]) or "")[:4]
                if eff.isdigit() and 1900 < int(eff) <= year:
                    e.plan_since = min(e.plan_since or 9999, int(eff))
                finals.setdefault(ein, []).append((row.get(col["final"]) or "").strip() == "1")
                signer = (row.get(col["signer"]) or "").strip()
                if not signer:
                    # the plan administrator signs most filings; take it only when the administrator is the
                    # employer itself (same EIN, "same as sponsor" ticked, or no separate administrator named)
                    admin_ein = (row.get(col["admin_ein"]) or "").strip()
                    if admin_ein in ("", ein) or (row.get(col["admin_same"]) or "").strip() == "1":
                        signer = (row.get(col["admin_signer"]) or "").strip()
                if signer and not e.signer:
                    e.signer = signer
    for ein, flags in finals.items():
        out[ein].final_filing = all(flags)
    return out


def employers(years: list[int], codes: set[str] | None = None) -> dict[str, Employer]:
    """The latest year's employers, with headcount from the earliest year attached for growth."""
    years = sorted(years)
    latest = read_year(years[-1], codes)
    if len(years) > 1:
        before = read_year(years[0], None if not codes else codes)
        for ein, e in latest.items():
            if ein in before:
                e.active_before = before[ein].active
                e.plan_since = min(x for x in (e.plan_since, before[ein].plan_since) if x) \
                    if (e.plan_since or before[ein].plan_since) else None
            e.years_compared = (years[0], years[-1])
    return latest
