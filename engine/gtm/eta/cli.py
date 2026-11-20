"""Command line for the ETA search. Registered on the main `gtm` parser (gtm.cli.build_parser).

    python -m gtm --client eta eta-discover --dry-run          # searches per SIC code, calls nothing
    python -m gtm --client eta eta-discover --code 71200 --max-per-code 100
    python -m gtm --client eta eta-enrich --limit 50           # profile, accounts, owners
    python -m gtm --client eta eta-screen                      # sieve 1 + evidence ledger
    python -m gtm --client eta eta-list --top 25               # ranked CSV in data/eta/
    python -m gtm --client eta eta-run --max-per-code 200 --limit 200   # all of the above
    python -m gtm --client eta eta-stats
    python -m gtm --client eta eta-evidence 01234567           # the evidence ledger for one company
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import yaml

from gtm import db
from gtm.config import data_dir, load_client
from gtm.eta import discover, enrich, screen, store

VENDOR = "companies_house"


def _limits(cfg) -> dict:
    path = Path(cfg.root) / "limits.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return (data or {}).get("companies_house", {})


def make_client(cfg, max_requests: int | None = None):
    from gtm.sources.companies_house import CompaniesHouseClient

    lim = _limits(cfg)
    return CompaniesHouseClient(per_window=int(lim.get("requests_per_5_min", 550)),
                                max_requests=max_requests or int(lim.get("max_requests_per_run", 5000)))


def _setup(args):
    cfg = load_client(args.client)
    return cfg, store.load_eta(cfg), store.connect()


def _logged(conn, cfg, layer: str, label: str, params: dict, fn, ch):
    """Run one step inside the shared runs ledger (cost is $0: Companies House is free)."""
    from gtm.sources.companies_house import RequestCapReached

    run_id = db.start_run(conn, cfg.slug, layer, VENDOR, label, 0.0, params)
    before = ch.requests_made
    try:
        result = fn()
    except RequestCapReached as exc:
        db.finish_run(conn, run_id, "stopped", ch.requests_made - before, 0.0, str(exc))
        print(f"Stopped: {exc} Re-run to continue where it stopped.")
        return None
    except Exception as exc:
        db.finish_run(conn, run_id, "failed", ch.requests_made - before, 0.0, str(exc)[:300])
        raise
    db.finish_run(conn, run_id, "succeeded", ch.requests_made - before, 0.0, json.dumps(result)[:500])
    return result


# ---------- commands ----------

def cmd_discover(args, ch=None) -> int:
    cfg, eta, conn = _setup(args)
    plans = discover.plan(eta, conn, cfg.slug, args.code, args.max_per_code)
    if not plans:
        print("Nothing to search: every code is exhausted or none is listed in eta.yaml.")
        return 1
    print(f"ETA discovery for {cfg.slug}: {len(plans)} SIC code(s), up to {sum(p.max_items for p in plans)} companies, "
          f"incorporated by {eta.get('search', {}).get('incorporated_to')}. Companies House is free.")
    for p in plans:
        print(f"  - {p.code} {p.label}: from result {p.start_index}, up to {p.max_items}")
    if args.dry_run:
        print("Dry run: nothing was called.")
        return 0
    ch = ch or make_client(cfg)
    results = _logged(conn, cfg, "ETA-discover", ",".join(p.code for p in plans),
                      {"codes": [p.code for p in plans]}, lambda: discover.run(ch, conn, cfg.slug, eta, plans), ch)
    for r in results or []:
        dropped = ", ".join(f"{k} {v}" for k, v in sorted(r.dropped.items())) or "none"
        more = "all read" if r.exhausted else "more next run"
        print(f"{r.code}: register hits {r.hits}, read {r.fetched}, new {r.new}, already known {r.duplicates}, "
              f"dropped: {dropped} ({more}).")
    print(f"Requests used: {ch.requests_made}.")
    return 0


def cmd_enrich(args, ch=None) -> int:
    cfg, eta, conn = _setup(args)
    steps = [s.strip() for s in (args.steps or "profile,accounts,owners").split(",") if s.strip()]
    ch = ch or make_client(cfg)
    if "profile" in steps:
        r = _logged(conn, cfg, "ETA-profile", "profile", {"limit": args.limit},
                    lambda: enrich.profile_step(ch, conn, cfg.slug, eta, args.limit), ch)
        if r:
            dropped = ", ".join(f"{k} {v}" for k, v in sorted(r["dropped"].items())) or "none"
            print(f"Profile: kept {r['profiled']}, dropped: {dropped}; not on the register {r['missing']}.")
    if "accounts" in steps:
        r = _logged(conn, cfg, "ETA-accounts", "accounts", {"limit": args.limit},
                    lambda: enrich.accounts_step(ch, conn, cfg.slug, eta, args.limit), ch)
        if r:
            print(f"Accounts: read {r['read']} companies ({r['periods']} numbers); "
                  f"no online accounts {r['no_online_accounts']}.")
    if "owners" in steps:
        r = _logged(conn, cfg, "ETA-owners", "owners", {"limit": args.limit},
                    lambda: enrich.owners_step(ch, conn, cfg.slug, eta, args.limit), ch)
        if r:
            print(f"Owners: {r['companies']} companies, {r['pscs']} owners, {r['directors']} directors.")
    print(f"Requests used: {ch.requests_made}.")
    return 0


def cmd_screen(args) -> int:
    cfg, eta, conn = _setup(args)
    r = screen.run(conn, cfg.slug, eta, rescreen=args.rescreen)
    print(f"Sieve 1: pass {r['pass']}, review {r['review']}, fail {r['fail']}.")
    return 0


def cmd_qualify(args, jev=None, fetcher=None) -> int:
    from gtm.eta import qualify

    cfg, eta, conn = _setup(args)
    rows = qualify.candidates(conn, cfg.slug)[: args.limit or None]
    print(f"Sieve 2 for {cfg.slug}: {len(rows)} sieve-1 survivors (pass/review). Stanford industry scorecard per SIC "
          f"code and Hamilton Helmer's 7 Powers per company, with TypeSafe Jev 1.14.")
    if args.dry_run:
        print("Dry run: no website fetched, no Jev call made.")
        return 0
    r = qualify.run(conn, cfg, eta, fetcher=fetcher, jev=jev, limit=args.limit)
    print(f"Industries scored {r['industries_scored']}; websites found {r['websites_found']}; 7 Powers decided "
          f"{r['powers_decided']}. Qualified {r['qualified']}, watch {r['watch']}, not qualified {r['not_qualified']}.")
    for i, q in enumerate(qualify.qualified(conn, cfg.slug)[:10], 1):
        b = q["breakdown"]
        print(f"  {i:>2}. {q['score']:>5} {q['verdict']:<9} {q['company_number']} {q['name'][:38]:<38} "
              f"industry {b.get('industry_score') or '?'}/30, powers {', '.join(b.get('clear_powers') or []) or '-'}")
    return 0


LIST_COLUMNS = ["rank", "verdict", "score", "company_number", "name", "search_code", "locality", "postal_code",
                "incorporated", "years", "accounts_type", "period", "turnover", "operating_margin", "net_assets",
                "cash", "net_debt", "employees", "retained_growth_years", "owner_age", "owner_band", "directors",
                "directors_under_55", "has_charges", "hard_fails", "register"]


def cmd_list(args) -> int:
    cfg, _, conn = _setup(args)
    verdicts = tuple(v.strip() for v in args.verdict.split(","))
    rows = screen.ranked(conn, cfg.slug, verdicts)[: args.top or None]
    out = Path(args.out) if args.out else data_dir() / "eta" / f"shortlist-{date.today():%Y%m%d}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LIST_COLUMNS)
        for i, r in enumerate(rows, 1):
            m = r["metrics"]
            w.writerow([i, r["verdict"], r["score"], r["company_number"], r["name"], r["search_code"], r["locality"],
                        r["postal_code"], r["incorporated"], m.get("years"), r["accounts_type"], m.get("period"),
                        m.get("turnover"), m.get("operating_margin"), m.get("net_assets"), m.get("cash"),
                        m.get("net_debt"), m.get("employees"), m.get("retained_growth_years"), m.get("owner_age"),
                        m.get("owner_band"), m.get("directors"), m.get("directors_under_55"), r["has_charges"],
                        ";".join(r["hard_fails"]), store.register_url(r["company_number"])])
    print(f"Wrote {len(rows)} companies ({'/'.join(verdicts)}) to {out}")
    for i, r in enumerate(rows[:10], 1):
        m = r["metrics"]
        print(f"  {i:>2}. {r['score']:>5} {r['verdict']:<6} {r['company_number']} {r['name'][:40]:<40} "
              f"owner {m.get('owner_age') or '?'}, employees {m.get('employees') or '?'}")
    return 0


def cmd_run(args) -> int:
    cfg, eta, conn = _setup(args)
    ch = make_client(cfg)
    if not args.skip_discover:
        args.code, args.dry_run = args.code, False
        cmd_discover(args, ch)
    cmd_enrich(args, ch)
    args.rescreen = False
    cmd_screen(args)
    if args.qualify:
        args.dry_run = False
        cmd_qualify(args)
    args.verdict, args.out = "pass,review", None
    return cmd_list(args)


def cmd_stats(args) -> int:
    cfg, _, conn = _setup(args)
    print(f"ETA search ({cfg.slug}):")
    for r in conn.execute("SELECT stage, COUNT(*) n FROM eta_companies WHERE client=? GROUP BY stage ORDER BY n DESC",
                          (cfg.slug,)):
        print(f"  {r['stage']:<14} {r['n']}")
    for r in conn.execute("SELECT stage_reason, COUNT(*) n FROM eta_companies WHERE client=? AND stage='dropped'"
                          " GROUP BY stage_reason ORDER BY n DESC LIMIT 10", (cfg.slug,)):
        print(f"    dropped: {r['stage_reason']:<28} {r['n']}")
    for r in conn.execute("SELECT verdict, COUNT(*) n FROM eta_screen WHERE client=? AND sieve=1 GROUP BY verdict",
                          (cfg.slug,)):
        print(f"  sieve 1 {r['verdict']:<7} {r['n']}")
    month = conn.execute("SELECT COALESCE(SUM(items),0) FROM runs WHERE client=? AND vendor=?"
                         " AND substr(started_at,1,7)=strftime('%Y-%m','now')", (cfg.slug, VENDOR)).fetchone()[0]
    print(f"  Companies House requests this month: {month}")
    return 0


def cmd_evidence(args) -> int:
    cfg, _, conn = _setup(args)
    rows = store.evidence(conn, cfg.slug, args.company_number)
    if not rows:
        print("No evidence recorded for that company number.")
        return 1
    for r in rows:
        line = f"{r['claim']:<38} {r['status']:<15} {r['value'] or '-'}"
        if r["next_step"]:
            line += f"  -> {r['next_step']}"
        print(line)
    return 0


def register(sub) -> None:
    d = sub.add_parser("eta-discover", help="ETA: find UK companies by SIC code and age (Companies House, free)")
    d.add_argument("--code", action="append", help="SIC code from eta.yaml (repeatable; default all)")
    d.add_argument("--max-per-code", type=int, help="companies to read per code this run")
    d.add_argument("--dry-run", action="store_true", help="show the searches, call nothing")
    d.set_defaults(func=cmd_discover)

    e = sub.add_parser("eta-enrich", help="ETA: company profile, filed accounts (iXBRL) and owners")
    e.add_argument("--limit", type=int, help="companies per step")
    e.add_argument("--steps", help="comma list of profile,accounts,owners (default all)")
    e.set_defaults(func=cmd_enrich)

    s = sub.add_parser("eta-screen", help="ETA: sieve 1 on public numbers, score and evidence ledger")
    s.add_argument("--rescreen", action="store_true", help="also re-screen companies screened before")
    s.set_defaults(func=cmd_screen)

    li = sub.add_parser("eta-list", help="ETA: ranked CSV of screened companies in data/eta/")
    li.add_argument("--verdict", default="pass,review", help="comma list of pass,review,fail")
    li.add_argument("--top", type=int, help="only the first N")
    li.add_argument("--out", help="CSV path (default data/eta/shortlist-YYYYMMDD.csv)")
    li.set_defaults(func=cmd_list)

    r = sub.add_parser("eta-run", help="ETA: discover, enrich, screen and list in one go")
    r.add_argument("--code", action="append", help="SIC code from eta.yaml (repeatable; default all)")
    r.add_argument("--max-per-code", type=int, help="companies to read per code this run")
    r.add_argument("--limit", type=int, help="companies per enrichment step")
    r.add_argument("--steps", help="comma list of profile,accounts,owners (default all)")
    r.add_argument("--skip-discover", action="store_true", help="only work through companies already found")
    r.add_argument("--top", type=int, help="list only the first N")
    r.add_argument("--qualify", action="store_true", help="also run sieve 2 (Jev 1.14: industry + 7 Powers)")
    r.set_defaults(func=cmd_run)

    q = sub.add_parser("eta-qualify", help="ETA sieve 2: Stanford industry scorecard + 7 Powers (Jev 1.14)")
    q.add_argument("--limit", type=int, help="companies to qualify this run")
    q.add_argument("--dry-run", action="store_true", help="show how many would be qualified, call nothing")
    q.set_defaults(func=cmd_qualify)

    st = sub.add_parser("eta-stats", help="ETA: companies per stage, sieve verdicts, requests this month")
    st.set_defaults(func=cmd_stats)

    ev = sub.add_parser("eta-evidence", help="ETA: the evidence ledger for one company")
    ev.add_argument("company_number")
    ev.set_defaults(func=cmd_evidence)
