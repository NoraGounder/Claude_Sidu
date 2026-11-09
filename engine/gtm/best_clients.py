"""The client's best customers, used as the model for "who should we find more of?".

Mithun lists his best clients in clients/<client>/private/best_clients.csv (gitignored; see
best_clients.example.csv). `import_best_clients`:
  1. puts every best client on the suppression list: current clients are never emailed;
  2. crawls each homepage (free, robots.txt respected) for a short description;
  3. stores the profiles in the best_clients table (data/, local only).
Layer 2 then gives TypeSafe Jev 1.14 these profiles (no names, no personal data) and asks how similar
each prospect is to them. The answer adds `jev_lookalike` fit points and can lift a very similar
company to Tier 2 (scoring.yaml).
"""

from __future__ import annotations

import csv

from gtm import db
from gtm.config import ClientConfig
from gtm.normalize import normalize_domain

MAX_PROFILES = 10           # keeps each Jev request small
EXCERPT_CHARS = 300


def read_rows(cfg: ClientConfig) -> list[dict[str, str]]:
    path = cfg.private_dir / "best_clients.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in row.items() if k}
                for row in csv.DictReader(fh) if (row.get("domain") or row.get("name"))]


def import_best_clients(cfg: ClientConfig, conn, fetcher=None) -> dict:
    """Suppress, crawl and store the best clients. Returns a summary; crawling is free."""
    from gtm.crawl import Fetcher

    rows = read_rows(cfg)
    fetcher = fetcher or Fetcher()           # homepage only; the Fetcher never raises
    summary = {"clients": len(rows), "crawled": 0, "suppressed": 0, "in_prospect_list": 0}
    conn.execute("DELETE FROM best_clients WHERE client=?", (cfg.slug,))
    for row in rows:
        domain = normalize_domain(row.get("domain") or "") or None
        if domain:
            db.add_suppression(conn, cfg.slug, "domain", domain, "best client (current customer)")
            summary["suppressed"] += 1
        if row.get("name"):
            db.add_suppression(conn, cfg.slug, "company", row["name"].lower(), "best client (current customer)")
        title = excerpt = None
        if domain:
            home = fetcher.get("https://" + domain)
            if home.ok:
                title, excerpt = home.title[:200], home.text[:EXCERPT_CHARS]
                summary["crawled"] += 1
            if conn.execute("SELECT 1 FROM accounts WHERE client=? AND domain=?", (cfg.slug, domain)).fetchone():
                summary["in_prospect_list"] += 1
        conn.execute(
            "INSERT INTO best_clients(client, name, domain, industry, employees, why_they_bought, home_title,"
            " home_excerpt, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (cfg.slug, row.get("name"), domain, row.get("industry"), row.get("employees"),
             row.get("why_they_bought"), title, excerpt, db.now_iso()))
    conn.commit()
    return summary


def jev_profiles(cfg: ClientConfig, conn) -> list[dict]:
    """Anonymous profiles for Jev: what they do, size, industry, why they bought. No names or domains."""
    rows = conn.execute(
        "SELECT industry, employees, why_they_bought, home_title, home_excerpt FROM best_clients"
        " WHERE client=? ORDER BY id LIMIT ?", (cfg.slug, MAX_PROFILES)).fetchall()
    profiles = []
    for r in rows:
        p = {"industry": r["industry"], "employees": r["employees"], "why_they_bought": r["why_they_bought"],
             "what_they_do": " ".join(filter(None, [r["home_title"], r["home_excerpt"]]))[:EXCERPT_CHARS]}
        p = {k: v for k, v in p.items() if v}
        if p:
            profiles.append(p)
    return profiles
