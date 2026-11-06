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


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or data_dir() / "engine.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
