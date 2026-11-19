"""Tables for the ETA search, next to the lead engine's tables in data/engine.db (gitignored).

eta_companies  one row per UK company found, with its stage in the pipeline
eta_financials one number per company, period end and metric, with the filing it came from
eta_owners     persons with significant control and directors (public register data)
eta_evidence   the evidence ledger: every claim, its value, its status and the next step to verify it
eta_screen     the latest sieve result per company
eta_progress   where each search code continues on the next run
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from gtm import db
from gtm.config import ClientConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_companies (
    client            TEXT NOT NULL,
    company_number    TEXT NOT NULL,
    name              TEXT NOT NULL,
    company_status    TEXT,
    company_type      TEXT,
    incorporated      TEXT,
    sic_codes         TEXT NOT NULL DEFAULT '[]',
    search_code       TEXT,
    locality          TEXT,
    postal_code       TEXT,
    region            TEXT,
    accounts_type     TEXT,
    accounts_made_up_to TEXT,
    accounts_overdue  INTEGER,
    has_charges       INTEGER,
    has_insolvency    INTEGER,
    stage             TEXT NOT NULL,      -- found | profiled | accounts_read | owners_read | screened | dropped
    stage_reason      TEXT,
    source            TEXT NOT NULL,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
CREATE INDEX IF NOT EXISTS ix_eta_companies_stage ON eta_companies(client, stage);

CREATE TABLE IF NOT EXISTS eta_financials (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    metric          TEXT NOT NULL,
    value           REAL NOT NULL,
    concept         TEXT,
    source_url      TEXT,
    filing_date     TEXT,
    read_at         TEXT NOT NULL,
    PRIMARY KEY (client, company_number, period_end, metric)
);

CREATE TABLE IF NOT EXISTS eta_owners (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    person_key      TEXT NOT NULL,
    kind            TEXT NOT NULL,         -- psc_individual | psc_corporate | psc_other | director
    name            TEXT,
    role            TEXT,
    birth_year      INTEGER,
    birth_month     INTEGER,
    appointed_on    TEXT,
    ceased_on       TEXT,
    ownership       TEXT,                  -- share band from the PSC natures of control, e.g. 75-100
    source          TEXT NOT NULL,
    read_at         TEXT NOT NULL,
    PRIMARY KEY (client, company_number, person_key)
);

CREATE TABLE IF NOT EXISTS eta_evidence (
    id              INTEGER PRIMARY KEY,
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    claim           TEXT NOT NULL,
    value           TEXT,
    status          TEXT NOT NULL CHECK (status IN ('public', 'seller_reported', 'unverified', 'unknown')),
    source          TEXT,
    next_step       TEXT,
    recorded_at     TEXT NOT NULL,
    UNIQUE (client, company_number, claim)
);

CREATE TABLE IF NOT EXISTS eta_screen (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    sieve           INTEGER NOT NULL,
    verdict         TEXT NOT NULL,          -- pass | review | fail
    score           REAL NOT NULL,
    hard_fails      TEXT NOT NULL DEFAULT '[]',
    breakdown       TEXT NOT NULL DEFAULT '{}',
    metrics         TEXT NOT NULL DEFAULT '{}',
    screened_at     TEXT NOT NULL,
    PRIMARY KEY (client, company_number, sieve)
);

CREATE TABLE IF NOT EXISTS eta_progress (
    client       TEXT NOT NULL,
    code         TEXT NOT NULL,
    next_start   INTEGER NOT NULL DEFAULT 0,
    hits         INTEGER,
    exhausted    INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (client, code)
);
"""

REGISTER = "https://find-and-update.company-information.service.gov.uk/company/"


def connect(path: Path | None = None):
    conn = db.connect(path)
    conn.executescript(SCHEMA)
    return conn


def load_eta(cfg: ClientConfig) -> dict:
    path = Path(cfg.root) / "eta.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: the ETA commands need a buy box (see clients/eta/eta.yaml).")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def register_url(number: str) -> str:
    return REGISTER + number


# ---------- companies ----------

def upsert_company(conn, client: str, row: dict) -> str:
    """Insert a found company or refresh last_seen. Returns 'new' or 'duplicate'."""
    ts = db.now_iso()
    existing = conn.execute("SELECT 1 FROM eta_companies WHERE client=? AND company_number=?",
                            (client, row["company_number"])).fetchone()
    if existing:
        conn.execute("UPDATE eta_companies SET last_seen=? WHERE client=? AND company_number=?",
                     (ts, client, row["company_number"]))
        return "duplicate"
    conn.execute(
        "INSERT INTO eta_companies(client, company_number, name, company_status, company_type, incorporated,"
        " sic_codes, search_code, locality, postal_code, region, stage, stage_reason, source, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (client, row["company_number"], row["name"], row.get("company_status"), row.get("company_type"),
         row.get("incorporated"), json.dumps(row.get("sic_codes", [])), row.get("search_code"),
         row.get("locality"), row.get("postal_code"), row.get("region"), row.get("stage", "found"),
         row.get("stage_reason"), row.get("source", "companies_house:advanced_search"), ts, ts),
    )
    return "new"


def set_stage(conn, client: str, number: str, stage: str, reason: str | None = None, **fields) -> None:
    cols = ["stage=?", "stage_reason=?"] + [f"{k}=?" for k in fields]
    conn.execute(f"UPDATE eta_companies SET {', '.join(cols)} WHERE client=? AND company_number=?",
                 (stage, reason, *fields.values(), client, number))


def companies_at(conn, client: str, stage: str, limit: int | None = None) -> list:
    sql = "SELECT * FROM eta_companies WHERE client=? AND stage=? ORDER BY first_seen, company_number"
    params: tuple = (client, stage)
    if limit:
        sql += " LIMIT ?"
        params += (limit,)
    return conn.execute(sql, params).fetchall()


# ---------- financials, owners, evidence ----------

def save_financial(conn, client: str, number: str, period_end: str, metric: str, value: float,
                   concept: str | None, source_url: str | None, filing_date: str | None) -> None:
    conn.execute(
        "INSERT INTO eta_financials(client, company_number, period_end, metric, value, concept, source_url,"
        " filing_date, read_at) VALUES (?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(client, company_number, period_end, metric) DO UPDATE SET value=excluded.value,"
        " concept=excluded.concept, source_url=excluded.source_url, filing_date=excluded.filing_date,"
        " read_at=excluded.read_at"
        " WHERE excluded.filing_date >= COALESCE(eta_financials.filing_date, '')",
        (client, number, period_end, metric, value, concept, source_url, filing_date, db.now_iso()),
    )


def financials(conn, client: str, number: str) -> dict[str, dict[str, float]]:
    """{period_end: {metric: value}}, newest period last."""
    out: dict[str, dict[str, float]] = {}
    for r in conn.execute("SELECT period_end, metric, value FROM eta_financials WHERE client=? AND company_number=?"
                          " ORDER BY period_end", (client, number)):
        out.setdefault(r["period_end"], {})[r["metric"]] = r["value"]
    return out


def save_owner(conn, client: str, number: str, owner: dict) -> None:
    conn.execute(
        "INSERT INTO eta_owners(client, company_number, person_key, kind, name, role, birth_year, birth_month,"
        " appointed_on, ceased_on, ownership, source, read_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(client, company_number, person_key) DO UPDATE SET kind=excluded.kind, name=excluded.name,"
        " role=excluded.role, birth_year=excluded.birth_year, birth_month=excluded.birth_month,"
        " appointed_on=excluded.appointed_on, ceased_on=excluded.ceased_on, ownership=excluded.ownership,"
        " source=excluded.source, read_at=excluded.read_at",
        (client, number, owner["person_key"], owner["kind"], owner.get("name"), owner.get("role"),
         owner.get("birth_year"), owner.get("birth_month"), owner.get("appointed_on"), owner.get("ceased_on"),
         owner.get("ownership"), owner["source"], db.now_iso()),
    )


def owners(conn, client: str, number: str) -> list:
    return conn.execute("SELECT * FROM eta_owners WHERE client=? AND company_number=?", (client, number)).fetchall()


def record_evidence(conn, client: str, number: str, claim: str, value, status: str,
                    source: str | None = None, next_step: str | None = None) -> None:
    """One claim in the evidence ledger. A later reading of the same claim replaces the earlier one,
    except that a claim the owner has already confirmed or a person has checked is never downgraded
    back to public or unknown by an automatic re-run."""
    current = conn.execute("SELECT status FROM eta_evidence WHERE client=? AND company_number=? AND claim=?",
                           (client, number, claim)).fetchone()
    if current and current["status"] in ("seller_reported", "unverified") and status in ("public", "unknown"):
        return
    conn.execute(
        "INSERT INTO eta_evidence(client, company_number, claim, value, status, source, next_step, recorded_at)"
        " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(client, company_number, claim) DO UPDATE SET value=excluded.value,"
        " status=excluded.status, source=excluded.source, next_step=excluded.next_step,"
        " recorded_at=excluded.recorded_at",
        (client, number, claim, None if value is None else str(value), status, source, next_step, db.now_iso()),
    )


def evidence(conn, client: str, number: str) -> list:
    return conn.execute("SELECT * FROM eta_evidence WHERE client=? AND company_number=? ORDER BY id",
                        (client, number)).fetchall()


def save_screen(conn, client: str, number: str, sieve: int, verdict: str, score: float, hard_fails: list,
                breakdown: dict, metrics: dict) -> None:
    conn.execute(
        "INSERT INTO eta_screen(client, company_number, sieve, verdict, score, hard_fails, breakdown, metrics,"
        " screened_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(client, company_number, sieve) DO UPDATE SET"
        " verdict=excluded.verdict, score=excluded.score, hard_fails=excluded.hard_fails,"
        " breakdown=excluded.breakdown, metrics=excluded.metrics, screened_at=excluded.screened_at",
        (client, number, sieve, verdict, score, json.dumps(hard_fails), json.dumps(breakdown),
         json.dumps(metrics), db.now_iso()),
    )


# ---------- search progress ----------

def progress(conn, client: str, code: str) -> dict:
    row = conn.execute("SELECT * FROM eta_progress WHERE client=? AND code=?", (client, code)).fetchone()
    return dict(row) if row else {"next_start": 0, "hits": None, "exhausted": 0}


def set_progress(conn, client: str, code: str, next_start: int, hits: int | None, exhausted: bool) -> None:
    conn.execute(
        "INSERT INTO eta_progress(client, code, next_start, hits, exhausted, updated_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(client, code) DO UPDATE SET next_start=excluded.next_start, hits=excluded.hits,"
        " exhausted=excluded.exhausted, updated_at=excluded.updated_at",
        (client, code, next_start, hits, int(exhausted), db.now_iso()),
    )
