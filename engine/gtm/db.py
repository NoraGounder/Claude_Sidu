"""SQLite working store. Lives in data/ (gitignored). HubSpot becomes the system of record in Layer 7."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from gtm.config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY,
    client          TEXT NOT NULL,
    linkedin_url    TEXT,
    linkedin_id     TEXT,
    name            TEXT NOT NULL,
    domain          TEXT,
    website         TEXT,
    country         TEXT,
    city            TEXT,
    industry        TEXT,
    employee_count  INTEGER,
    employee_range  TEXT,
    segments        TEXT NOT NULL DEFAULT '[]',
    source          TEXT NOT NULL,
    status          TEXT NOT NULL,
    status_reason   TEXT,
    raw_json        TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_accounts_linkedin ON accounts(client, linkedin_url)
    WHERE linkedin_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_accounts_domain ON accounts(client, domain);
CREATE INDEX IF NOT EXISTS ix_accounts_status ON accounts(client, status);

CREATE TABLE IF NOT EXISTS suppression (
    client    TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('domain', 'company', 'linkedin', 'email')),
    value     TEXT NOT NULL,
    reason    TEXT,
    added_at  TEXT NOT NULL,
    PRIMARY KEY (client, kind, value)
);

CREATE TABLE IF NOT EXISTS l2_scores (
    account_id      INTEGER PRIMARY KEY REFERENCES accounts(id),
    fit             INTEGER NOT NULL,
    signal          INTEGER NOT NULL,
    tier            TEXT NOT NULL,
    reachable       INTEGER NOT NULL,
    dutch_site      INTEGER NOT NULL,
    careers_url     TEXT,
    job_link_count  INTEGER DEFAULT 0,
    job_titles      TEXT DEFAULT '[]',
    flags           TEXT DEFAULT '[]',
    breakdown       TEXT DEFAULT '{}',
    scored_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    layer       TEXT NOT NULL,
    signal      TEXT NOT NULL,
    label       TEXT NOT NULL,
    url         TEXT NOT NULL,
    quote       TEXT,
    found_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_account ON evidence(account_id);

CREATE TABLE IF NOT EXISTS jev_decisions (
    account_id      INTEGER PRIMARY KEY REFERENCES accounts(id),
    model_id        TEXT NOT NULL,
    not_a_buyer     REAL,
    icp_fit         REAL,
    icp_confidence  REAL,
    titles_json     TEXT NOT NULL DEFAULT '{}',
    raw_answers     TEXT,
    decided_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS best_clients (
    id              INTEGER PRIMARY KEY,
    client          TEXT NOT NULL,
    name            TEXT,                   -- local only (data/, gitignored); never sent to Jev
    domain          TEXT,
    industry        TEXT,
    employees       TEXT,
    why_they_bought TEXT,
    home_title      TEXT,
    home_excerpt    TEXT,
    imported_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jev_calls (
    id             INTEGER PRIMARY KEY,
    client         TEXT NOT NULL,
    account_id     INTEGER,
    requested_model TEXT NOT NULL,
    model_id       TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cost_usd       REAL,
    latency_ms     INTEGER,
    request_id     TEXT,
    status         TEXT NOT NULL,
    error          TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY,
    client          TEXT NOT NULL,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    person_id       TEXT,
    full_name       TEXT,
    first_name      TEXT,
    last_name       TEXT,
    title           TEXT,
    linkedin_url    TEXT,
    country         TEXT,
    persona         TEXT,
    jev_relevance   REAL,
    rank            INTEGER,
    status          TEXT NOT NULL,      -- candidate | selected | email_found | no_email | skipped
    status_reason   TEXT,
    email           TEXT,
    email_status    TEXT,               -- as reported by the provider, e.g. DELIVERABLE, CATCH_ALL
    email_source    TEXT,
    data_source     TEXT NOT NULL,      -- where the personal data came from (GDPR Art. 14)
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_person ON contacts(client, account_id, person_id);
CREATE INDEX IF NOT EXISTS ix_contacts_status ON contacts(client, status);

CREATE TABLE IF NOT EXISTS l3_progress (
    account_id   INTEGER PRIMARY KEY REFERENCES accounts(id),
    searched_at  TEXT NOT NULL,
    found        INTEGER NOT NULL,
    credits      REAL
);

CREATE TABLE IF NOT EXISTS drafts (
    id                 INTEGER PRIMARY KEY,
    client             TEXT NOT NULL,
    contact_id         INTEGER NOT NULL UNIQUE REFERENCES contacts(id),
    language           TEXT NOT NULL,
    hook               TEXT NOT NULL,
    process            TEXT NOT NULL,
    subject            TEXT NOT NULL,
    steps_json         TEXT NOT NULL,      -- rendered emails, one per step, with their send day
    facts_json         TEXT NOT NULL,      -- every fact used, with its source URL
    jev_angle_p        REAL,
    qa_unsupported_p   REAL,
    status             TEXT NOT NULL,      -- preview | draft | needs_review | approved | rejected
    edited             INTEGER NOT NULL DEFAULT 0,
    review_note        TEXT,
    reviewed_at        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id             INTEGER PRIMARY KEY,
    client         TEXT NOT NULL,
    region         TEXT NOT NULL,
    smartlead_id   INTEGER NOT NULL,
    name           TEXT NOT NULL,
    timezone       TEXT NOT NULL,
    status         TEXT NOT NULL,          -- DRAFTED | ACTIVE | PAUSED | STOPPED
    created_at     TEXT NOT NULL,
    UNIQUE(client, region)
);

CREATE TABLE IF NOT EXISTS outbound (
    contact_id        INTEGER PRIMARY KEY REFERENCES contacts(id),
    client            TEXT NOT NULL,
    account_id        INTEGER NOT NULL,
    draft_id          INTEGER NOT NULL,
    campaign_id       INTEGER NOT NULL REFERENCES campaigns(id),
    smartlead_lead_id INTEGER,
    status            TEXT NOT NULL,       -- pushed | replied | bounced | unsubscribed | completed
    pushed_at         TEXT NOT NULL,
    last_sync_at      TEXT
);

CREATE TABLE IF NOT EXISTS replies (
    id            INTEGER PRIMARY KEY,
    client        TEXT NOT NULL,
    contact_id    INTEGER NOT NULL REFERENCES contacts(id),
    received_at   TEXT,
    text          TEXT,                    -- local only (data/, gitignored)
    category      TEXT,
    category_p    REAL,
    model_id      TEXT,
    handled       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    UNIQUE(client, contact_id, received_at)
);

CREATE TABLE IF NOT EXISTS segment_progress (
    client     TEXT NOT NULL,
    segment    TEXT NOT NULL,
    next_page  INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (client, segment)
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    client       TEXT NOT NULL,
    layer        TEXT NOT NULL,
    vendor       TEXT NOT NULL,
    label        TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    items        INTEGER DEFAULT 0,
    est_cost     REAL DEFAULT 0,
    actual_cost  REAL,
    params_json  TEXT,
    notes        TEXT
);
"""


MIGRATIONS = [
    ("l2_scores", "home_title", "TEXT"),
    ("l2_scores", "home_excerpt", "TEXT"),
    ("contacts", "verified_at", "TEXT"),
    ("contacts", "gate_checked_at", "TEXT"),
    ("jev_decisions", "lookalike", "REAL"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ctype in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or data_dir() / "engine.db"
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# ---------- suppression ----------

def add_suppression(conn, client: str, kind: str, value: str, reason: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO suppression(client, kind, value, reason, added_at) VALUES (?,?,?,?,?)",
        (client, kind, value.strip().lower(), reason, now_iso()),
    )


def suppressed_values(conn, client: str, kind: str) -> set[str]:
    rows = conn.execute("SELECT value FROM suppression WHERE client=? AND kind=?", (client, kind))
    return {r["value"] for r in rows}


# ---------- runs ledger ----------

def start_run(conn, client: str, layer: str, vendor: str, label: str, est_cost: float, params: dict) -> int:
    cur = conn.execute(
        "INSERT INTO runs(client, layer, vendor, label, started_at, status, est_cost, params_json)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (client, layer, vendor, label, now_iso(), "running", est_cost, json.dumps(params)),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn, run_id: int, status: str, items: int, actual_cost: float | None, notes: str = "") -> None:
    conn.execute(
        "UPDATE runs SET finished_at=?, status=?, items=?, actual_cost=?, notes=? WHERE id=?",
        (now_iso(), status, items, actual_cost, notes, run_id),
    )
    conn.commit()


def month_spend(conn, client: str, vendor: str) -> float:
    """Spend this calendar month (UTC). Uses actual cost when known, else the estimate."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    row = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(actual_cost, est_cost)), 0) AS spent FROM runs"
        " WHERE client=? AND vendor=? AND substr(started_at, 1, 7)=? AND status != 'dry_run'",
        (client, vendor, month),
    ).fetchone()
    return float(row["spent"])


# ---------- search progress (so monthly runs continue instead of re-buying page 1) ----------

def next_page(conn, client: str, segment: str) -> int:
    row = conn.execute(
        "SELECT next_page FROM segment_progress WHERE client=? AND segment=?", (client, segment)
    ).fetchone()
    return int(row["next_page"]) if row else 1


def set_next_page(conn, client: str, segment: str, page: int) -> None:
    conn.execute(
        "INSERT INTO segment_progress(client, segment, next_page, updated_at) VALUES (?,?,?,?)"
        " ON CONFLICT(client, segment) DO UPDATE SET next_page=excluded.next_page,"
        " updated_at=excluded.updated_at",
        (client, segment, page, now_iso()),
    )
    conn.commit()


# ---------- accounts ----------

def find_account(conn, client: str, linkedin_url: str | None, domain: str | None):
    if linkedin_url:
        row = conn.execute(
            "SELECT * FROM accounts WHERE client=? AND linkedin_url=?", (client, linkedin_url)
        ).fetchone()
        if row:
            return row
    if domain:
        return conn.execute(
            "SELECT * FROM accounts WHERE client=? AND domain=?", (client, domain)
        ).fetchone()
    return None


def upsert_account(conn, client: str, acc: dict, segment: str) -> str:
    """Insert a new account or refresh an existing one. Returns 'new' or 'duplicate'."""
    existing = find_account(conn, client, acc.get("linkedin_url"), acc.get("domain"))
    ts = now_iso()
    if existing:
        segments = set(json.loads(existing["segments"]))
        segments.add(segment)
        conn.execute(
            "UPDATE accounts SET last_seen=?, segments=?,"
            " website=COALESCE(website, ?), domain=COALESCE(domain, ?),"
            " employee_count=COALESCE(employee_count, ?) WHERE id=?",
            (ts, json.dumps(sorted(segments)), acc.get("website"), acc.get("domain"),
             acc.get("employee_count"), existing["id"]),
        )
        return "duplicate"
    conn.execute(
        "INSERT INTO accounts(client, linkedin_url, linkedin_id, name, domain, website, country, city,"
        " industry, employee_count, employee_range, segments, source, status, status_reason, raw_json,"
        " first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            client, acc.get("linkedin_url"), acc.get("linkedin_id"), acc["name"], acc.get("domain"),
            acc.get("website"), acc.get("country"), acc.get("city"), acc.get("industry"),
            acc.get("employee_count"), acc.get("employee_range"), json.dumps([segment]),
            acc["source"], acc["status"], acc.get("status_reason"), json.dumps(acc.get("raw", {})),
            ts, ts,
        ),
    )
    return "new"
