"""Capital partners, brokers and advisers for the ETA search (clients/eta/partners.yaml, decisions.md E13).

    search   BlitzAPI company search per kind (flat plan, records capped by limits.yaml blitzapi_records)
    check    read each firm's website (free) and ask TypeSafe Jev 1.14 whether it fits the kind, plus the one
             yes/no that matters most for that kind (e.g. "backs independent sponsors?")
    people   for firms that fit: the senior people by title (BlitzAPI), names and LinkedIn only, no emails
    export   data/eta/partners/<kind>.csv and summary.md, best first

Nothing here contacts anyone. Firms and people stay in data/engine.db and data/eta/partners/ (gitignored); every row
records where it came from.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from gtm import budget, db
from gtm.config import data_dir
from gtm.eta.qualify import _ask, price_key
from gtm.sources.jev import JevClient, check_policy

VENDOR = "blitzapi"
JEV_VENDOR = "openrouter"
PAGE = 50
LINK_WORDS = ("about", "criteria", "invest", "strategy", "approach", "focus", "services", "what-we-do", "practice",
              "transactions", "deals", "portfolio", "sponsor", "team")

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_partners (
    client       TEXT NOT NULL,
    domain       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    name         TEXT,
    website      TEXT,
    linkedin_url TEXT,
    city         TEXT,
    state        TEXT,
    size         TEXT,
    industry     TEXT,
    searches     TEXT NOT NULL,
    fit          REAL,
    check_value  REAL,
    verdict      TEXT,
    site_title   TEXT,
    model_id     TEXT,
    decided_at   TEXT,
    found_at     TEXT NOT NULL,
    PRIMARY KEY (client, domain)
);
CREATE TABLE IF NOT EXISTS eta_partner_people (
    client       TEXT NOT NULL,
    domain       TEXT NOT NULL,
    name         TEXT NOT NULL,
    title        TEXT,
    linkedin_url TEXT,
    source       TEXT NOT NULL,
    found_at     TEXT NOT NULL,
    PRIMARY KEY (client, domain, name)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def load(root: Path) -> dict:
    return yaml.safe_load((Path(root) / "partners.yaml").read_text(encoding="utf-8"))


def records_used(conn, client: str) -> int:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    row = conn.execute("SELECT COALESCE(SUM(items), 0) FROM runs WHERE client=? AND vendor=? AND started_at LIKE ?",
                       (client, VENDOR, f"{month}%")).fetchone()
    return int(row[0])


def records_cap(cfg) -> int:
    return int(cfg.limits.month_budget_usd.get("blitzapi_records") or 0)


# ---------- search ----------

def plans(conf: dict, kinds: list[str] | None = None) -> list[dict]:
    out = []
    for kind, k in conf["kinds"].items():
        if kinds and kind not in kinds:
            continue
        for s in k.get("searches") or []:
            company = {"hq": {"country_code": {"include": [conf.get("country", "US")]}},
                       "employee_count": {"min": conf["employees"]["min"], "max": conf["employees"]["max"]}}
            if s.get("industries"):
                company["industry"] = {"include": s["industries"]}
            if s.get("keywords"):
                company["keywords"] = {"include": s["keywords"]}
            out.append({"kind": kind, "name": s["name"], "company": company, "max_items": int(s.get("max_items", 100))})
    return out


def domain_of(company: dict) -> str | None:
    d = (company.get("domain") or company.get("website") or "").lower()
    d = d.split("://", 1)[-1].split("/", 1)[0]
    return d.removeprefix("www.") or None


def search(conn, cfg, conf: dict, api, kinds: list[str] | None = None) -> dict:
    """Run the BlitzAPI searches and store new firms. A firm found by several searches keeps its first kind."""
    ensure_schema(conn)
    ps = plans(conf, kinds)
    wanted = sum(p["max_items"] for p in ps)
    used, cap = records_used(conn, cfg.slug), records_cap(cfg)
    if used + wanted > cap:
        raise budget.BudgetExceeded(f"blitzapi: these searches could use {wanted} records, but only {cap - used} of "
                                    f"ETA's {cap} a month are left (limits.yaml blitzapi_records).")
    budget.check(conn, cfg, VENDOR, 0.0)
    out = {"searches": len(ps), "records": 0, "new": 0, "per_kind": {}}
    for p in ps:
        run_id = db.start_run(conn, cfg.slug, "eta_partners", VENDOR, f"{p['kind']}:{p['name']}", 0.0,
                              {"company": p["company"], "max_items": p["max_items"]})
        items, cursor = [], None
        try:
            while len(items) < p["max_items"]:
                data = api.search_companies(p["company"], min(PAGE, p["max_items"] - len(items)), cursor)
                page = data.get("results") or []
                items.extend(page)
                cursor = data.get("cursor")
                if not page or not cursor:
                    break
        except Exception as exc:
            db.finish_run(conn, run_id, "failed", len(items), 0.0, str(exc)[:300])
            raise
        db.finish_run(conn, run_id, "succeeded", len(items), 0.0, "")
        out["records"] += len(items)
        for c in items:
            dom = domain_of(c)
            if not dom:
                continue
            hq = c.get("hq") or {}
            prev = conn.execute("SELECT searches FROM eta_partners WHERE client=? AND domain=?",
                                (cfg.slug, dom)).fetchone()
            tag = f"blitzapi:{p['kind']}:{p['name']}"
            if prev:
                tags = sorted(set(json.loads(prev["searches"])) | {tag})
                conn.execute("UPDATE eta_partners SET searches=? WHERE client=? AND domain=?",
                             (json.dumps(tags), cfg.slug, dom))
                continue
            website = c.get("website") or f"https://{dom}"
            conn.execute("INSERT INTO eta_partners(client, domain, kind, name, website, linkedin_url, city, state, size,"
                         " industry, searches, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cfg.slug, dom, p["kind"], c.get("name"), website, c.get("linkedin_url"), hq.get("city"),
                          hq.get("state") or hq.get("region"), c.get("size"), c.get("industry"), json.dumps([tag]),
                          db.now_iso()))
            out["new"] += 1
            out["per_kind"][p["kind"]] = out["per_kind"].get(p["kind"], 0) + 1
        conn.commit()
    return out


# ---------- website check (Jev 1.14) ----------

def questions(k: dict) -> dict:
    return {
        "fit": {"type": "score", "instructions": "How well does this firm match this description? " + k["fit"]
                + " Judge only from the firm facts and website text given.",
                "criteria": ["Not this kind of firm", "Possibly", "Clearly this kind of firm"]},
        "check": {"type": "noul", "instructions": k["check"],
                  "criteria": {"true": "Yes, the website says so", "false": "No, or the website does not say"}},
    }


def site_text(fetcher, website: str, limit: int = 4000) -> tuple[str, str, bool]:
    home = fetcher.get(website)
    if not home.ok:
        return "", "", False
    parts, seen = [home.text], 0
    for link, anchor in home.links[:200]:
        if any(w in (link + " " + anchor).lower() for w in LINK_WORDS):
            sub = fetcher.get(link)
            seen += 1
            if sub.ok:
                parts.append(sub.text)
            if seen >= 4 or sum(len(p) for p in parts) > limit * 2:
                break
    return home.title, " ".join(parts)[:limit], True


def check(conn, cfg, conf: dict, fetcher=None, jev=None, limit: int | None = None) -> dict:
    ensure_schema(conn)
    check_policy(cfg.ai)
    rows = conn.execute("SELECT * FROM eta_partners WHERE client=? AND decided_at IS NULL ORDER BY found_at",
                        (cfg.slug,)).fetchall()[: limit or conf.get("max_sites_per_run", 400)]
    out = {"firms": len(rows), "decided": 0, "no_site": 0, "fit": 0, "maybe": 0, "no": 0}
    if not rows:
        return out
    budget.check(conn, cfg, JEV_VENDOR, budget.estimate(cfg, price_key(cfg), len(rows)))
    jev = jev or JevClient(cfg.ai)
    if fetcher is None:
        from gtm.crawl import default_fetcher
        fetcher = default_fetcher()
    bar = float(conf.get("fit_bar", 1.5))
    for r in rows:
        k = conf["kinds"][r["kind"]]
        title, text, ok = site_text(fetcher, r["website"])
        if not ok or len(text) < 200:
            conn.execute("UPDATE eta_partners SET verdict='no_site', decided_at=? WHERE client=? AND domain=?",
                         (db.now_iso(), cfg.slug, r["domain"]))
            out["no_site"] += 1
            conn.commit()
            continue
        state = {"firm": r["name"], "website": r["website"], "website_title": title, "linkedin_industry": r["industry"],
                 "size": r["size"], "location": ", ".join(x for x in (r["city"], r["state"]) if x),
                 "website_text": text}
        result = _ask(jev, conn, cfg, state, questions(k))
        fit = round(float(result.answers["fit"]["score"]), 2)
        chk = round(float(result.answers["check"]["noul"]), 2)
        verdict = "fit" if fit >= bar else "maybe" if fit >= 1.0 else "no"
        conn.execute("UPDATE eta_partners SET fit=?, check_value=?, verdict=?, site_title=?, model_id=?, decided_at=?"
                     " WHERE client=? AND domain=?", (fit, chk, verdict, title[:200], result.model_id, db.now_iso(),
                                                      cfg.slug, r["domain"]))
        out["decided"] += 1
        out[verdict] += 1
        conn.commit()
    return out


# ---------- people ----------

def people(conn, cfg, conf: dict, api, kinds: list[str] | None = None, per_firm: int = 2,
           limit: int | None = None) -> dict:
    """Senior people at firms that fit: names, titles and LinkedIn only (no emails until outreach is cleared)."""
    ensure_schema(conn)
    rows = [r for r in conn.execute(
        "SELECT p.* FROM eta_partners p WHERE p.client=? AND p.verdict='fit' AND p.linkedin_url IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM eta_partner_people x WHERE x.client=p.client AND x.domain=p.domain)"
        " ORDER BY p.check_value DESC, p.fit DESC", (cfg.slug,)).fetchall() if not kinds or r["kind"] in kinds]
    rows = rows[:limit] if limit else rows
    wanted = len(rows) * per_firm
    used, cap = records_used(conn, cfg.slug), records_cap(cfg)
    if used + wanted > cap:
        raise budget.BudgetExceeded(f"blitzapi: up to {wanted} records needed, {cap - used} left this month.")
    out = {"firms": len(rows), "people": 0}
    run_id = db.start_run(conn, cfg.slug, "eta_partners", VENDOR, "partner people", 0.0, {"firms": len(rows)})
    try:
        for r in rows:
            titles = conf["kinds"][r["kind"]].get("titles") or []
            cascade = [{"include_title": [t], "exclude_title": ["assistant", "intern", "analyst"], "location": ["WORLD"],
                        "include_headline_search": False} for t in titles][:10]
            for hit in api.people(r["linkedin_url"], cascade, per_firm):
                p = hit.get("person") or hit
                name = p.get("full_name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
                if not name:
                    continue
                current = [e for e in p.get("experiences") or [] if e.get("job_is_current")]
                title = (current[0].get("job_title") if current else None) or p.get("headline")
                conn.execute("INSERT OR IGNORE INTO eta_partner_people(client, domain, name, title, linkedin_url, source,"
                             " found_at) VALUES (?,?,?,?,?,?,?)",
                             (cfg.slug, r["domain"], name, title, p.get("linkedin_url"),
                              "blitzapi people search", db.now_iso()))
                out["people"] += 1
            conn.commit()
    finally:
        db.finish_run(conn, run_id, "succeeded", out["people"], 0.0, json.dumps(out))
        conn.commit()
    return out


# ---------- export ----------

def export(conn, cfg, conf: dict) -> dict:
    ensure_schema(conn)
    folder = data_dir() / "eta" / "partners"
    folder.mkdir(parents=True, exist_ok=True)
    counts, lines = {}, [f"# Partners for the ETA search, {db.now_iso()[:10]}", ""]
    for kind, k in conf["kinds"].items():
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM eta_partners WHERE client=? AND kind=? ORDER BY CASE verdict WHEN 'fit' THEN 0 WHEN 'maybe'"
            " THEN 1 ELSE 2 END, check_value DESC, fit DESC", (cfg.slug, kind))]
        ppl = {}
        for p in conn.execute("SELECT * FROM eta_partner_people WHERE client=?", (cfg.slug,)):
            ppl.setdefault(p["domain"], []).append(f"{p['name']} ({p['title'] or '-'})")
        fits = [r for r in rows if r["verdict"] in ("fit", "maybe")]
        with open(folder / f"{kind}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["verdict", "fit (0-2)", "check (0-1)", "firm", "website", "city", "state", "size", "people",
                        "found by"])
            for r in fits:
                w.writerow([r["verdict"], r["fit"], r["check_value"], r["name"], r["website"], r["city"], r["state"],
                            r["size"], "; ".join(ppl.get(r["domain"], [])), " ".join(json.loads(r["searches"]))])
        c = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("fit", "maybe", "no", "no_site")}
        c["found"], c["unchecked"] = len(rows), sum(1 for r in rows if r["verdict"] is None)
        c["strong"] = sum(1 for r in rows if r["verdict"] == "fit" and (r["check_value"] or 0) >= 0.5)
        counts[kind] = c
        lines += [f"## {k['label']}", "", f"When: {k['approach']}", "",
                  f"Found {c['found']}; fit {c['fit']} (strongest {c['strong']}), maybe {c['maybe']}, no {c['no']}, "
                  f"no usable site {c['no_site']}, not checked yet {c['unchecked']}.", "",
                  "| Firm | Where | Fit | Check | People |", "|---|---|---|---|---|"]
        for r in fits[:25]:
            lines.append(f"| [{r['name']}]({r['website']}) | {', '.join(x for x in (r['city'], r['state']) if x)} | "
                         f"{r['fit']} | {r['check_value']} | {'; '.join(ppl.get(r['domain'], [])) or '-'} |")
        lines.append("")
    (folder / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return {"folder": str(folder), "counts": counts}
