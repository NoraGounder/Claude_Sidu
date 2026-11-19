"""Market lists: for each segment, the companies its buyers work at that are hiring now (job postings,
BlitzAPI). Email 1 names three of them, so the prospect sees the work before being asked for anything.

A list is refreshed at most weekly (`markets --refresh`) and kept in data/markets/<segment>.json. Only
company names, posting titles, dates and links are stored: no people. Companies that are themselves in
the client's prospect list (vendors like the prospect) are never named, nor the prospect.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from gtm import db
from gtm.config import ClientConfig, data_dir

REFRESH_DAYS = 7   # default; markets.yaml refresh_days overrides


def load_config(cfg: ClientConfig) -> dict | None:
    path = Path(cfg.root) / "markets.yaml"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _path(cfg: ClientConfig, segment: str) -> Path:
    return data_dir() / "markets" / cfg.slug / f"{segment}.json"


def load_list(cfg: ClientConfig, segment: str) -> dict | None:
    p = _path(cfg, segment)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def refresh(cfg: ClientConfig, conn, force: bool = False, client=None, max_postings: int | None = None) -> dict:
    """Fetch job postings per segment and keep the hiring companies. Skips lists newer than a week."""
    from gtm.layers import l1_hiring
    from gtm.sources.blitz import BlitzClient

    conf = load_config(cfg) or {}
    max_postings = max_postings or conf.get("postings_per_segment", 50)
    out = {}
    for segment, spec in (conf.get("segments") or {}).items():
        current = load_list(cfg, segment)
        days = conf.get("refresh_days", REFRESH_DAYS)
        if current and not force and datetime.fromisoformat(current["refreshed_at"]) > datetime.now(timezone.utc) - timedelta(days=days):
            out[segment] = "fresh"
            continue
        l1_hiring.check_records(conn, cfg, max_postings)
        api = client or BlitzClient()
        job = {"title": {"include": spec["roles"]}, "date_posted": {"last_days": conf.get("posted_last_days", 30)}}
        if conf.get("exclude_title_words"):
            job["title"]["exclude"] = conf["exclude_title_words"]
        company = {"employee_count": {"min": conf.get("min_employees", 51), "max": conf.get("max_employees", 10000)},
                   "hq": {"country_code": {"include": spec.get("countries") or ["US"]}}}
        if spec.get("keywords"):
            company["keywords"] = {"include": spec["keywords"]}
        if conf.get("exclude_industries"):
            company["industry"] = {"exclude": conf["exclude_industries"]}
        run_id = db.start_run(conn, cfg.slug, "MARKET", l1_hiring.VENDOR, f"market:{segment}", 0.0, {"job": job, "company": company})
        data = api.jobs(job, company, max_postings)
        companies: dict[str, dict] = {}
        for p in data.get("results") or []:
            name = (p.get("company_name") or "").strip()
            if not name:
                continue
            c = companies.setdefault(name.lower(), {"name": name, "linkedin_url": p.get("company_linkedin_url"), "postings": []})
            c["postings"].append({"title": p.get("title"), "date": str(p.get("date_posted") or "")[:10], "url": p.get("url")})
        ranked = sorted(companies.values(), key=lambda c: (len(c["postings"]), max(x["date"] for x in c["postings"])), reverse=True)
        result = {"segment": segment, "role": spec["role_label"], "refreshed_at": datetime.now(timezone.utc).isoformat(),
                  "companies": ranked[:30]}
        path = _path(cfg, segment)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        db.finish_run(conn, run_id, "succeeded", len(data.get("results") or []), 0.0, f"{len(ranked)} companies")
        out[segment] = len(ranked)
    return out


def pick(cfg: ClientConfig, conn, account: dict, n: int = 3) -> dict | None:
    """Three hiring companies for this account's market, varied per account (not the same three for every
    email), never the account itself and never a company in the client's own prospect list."""
    segments = json.loads(account.get("segments") or "[]")
    lst = next((x for x in (load_list(cfg, s) for s in segments) if x and x.get("companies")), None)
    if not lst:
        return None
    own = {r[0].lower() for r in conn.execute("SELECT name FROM accounts WHERE client=?", (cfg.slug,))}
    me = (account.get("name") or "").lower()
    conf = load_config(cfg) or {}
    never = [w.lower() for w in conf.get("never_name", [])]       # vendors, integrators, recruiters
    pool = [c for c in lst["companies"][:15]
            if c["name"].lower() not in own and c["name"].lower() != me and me not in c["name"].lower()
            and not any(w in c["name"].lower() for w in never)][:12]
    if len(pool) < n:
        return None
    start = int(hashlib.sha1(str(account["id"]).encode()).hexdigest(), 16) % len(pool)
    chosen = [pool[(start + i) % len(pool)] for i in range(n)]
    from gtm.layers.l5_copy import clean_company
    names = [clean_company(c["name"], ["inc", "llc", "ltd", "plc", "corp", "corporation", "co", "limited", "group"],
                           [" - ", " | "]) for c in chosen]
    return {"names": names, "role": lst["role"], "sources": [c["postings"][0]["url"] for c in chosen],
            "refreshed_at": lst["refreshed_at"]}


def join_names(names: list[str]) -> str:
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
