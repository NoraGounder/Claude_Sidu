"""Which country a company in the ETA tables belongs to, from its id.

UK companies keep their Companies House number (8 characters). US companies are "US-<first PPP loan number>",
Polish companies "PL-<KRS number>". Industry codes carry their system the same way in sieve 2:
a bare code is a UK SIC code, "naics:238220" and "pkd:43.22.Z" are the others.
"""

from __future__ import annotations

COUNTRY = {"GB": "United Kingdom", "US": "United States", "PL": "Poland"}
CODE_SYSTEM = {"GB": "UK SIC 2007", "US": "NAICS 2017", "PL": "PKD 2007"}
CODE_PREFIX = {"GB": "", "US": "naics:", "PL": "pkd:"}


def market_of(company_id: str) -> str:
    head = (company_id or "")[:3]
    return {"US-": "US", "PL-": "PL"}.get(head, "GB")


def industry_key(company_id: str, code: str | None) -> str | None:
    if not code:
        return None
    return CODE_PREFIX[market_of(company_id)] + str(code)


def code_labels(eta: dict) -> dict[str, str]:
    """Every industry key in the config -> its label, across markets."""
    out = {str(k): v for k, v in ((eta.get("search") or {}).get("sic_codes") or {}).items()}
    out.update({f"naics:{k}": v for k, v in ((eta.get("us") or {}).get("naics_codes") or {}).items()})
    out.update({f"pkd:{k}": v for k, v in ((eta.get("pl") or {}).get("pkd_codes") or {}).items()})
    return out


def split_key(key: str) -> tuple[str, str]:
    """'naics:238220' -> ('US', '238220'); '43220' -> ('GB', '43220')."""
    for market, prefix in CODE_PREFIX.items():
        if prefix and key.startswith(prefix):
            return market, key[len(prefix):]
    return "GB", key
