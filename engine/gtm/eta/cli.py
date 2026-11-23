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
from datetime import date, timedelta
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
    db.finish_run(conn, run_id, "succeeded", ch.requests_made - before, 0.0, json.dumps(result, default=lambda o: getattr(o, "__dict__", str(o)))[:500])
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
    if getattr(args, "reparse", False):
        rp = enrich.reparse_cached(conn, cfg.slug)
        print(f"Re-read {rp['documents']} cached filings ({rp['numbers']} numbers) with the current parser.")
        args.rescreen = True
    r = screen.run(conn, cfg.slug, eta, rescreen=args.rescreen)
    print(f"Sieve 1: pass {r['pass']}, review {r['review']}, fail {r['fail']}.")
    return 0


def cmd_qualify(args, jev=None, fetcher=None) -> int:
    from gtm.eta import qualify

    cfg, eta, conn = _setup(args)
    rows = qualify.candidates(conn, cfg.slug, market=args.market)[: args.limit or None]
    print(f"Sieve 2 for {cfg.slug}: {len(rows)} sieve-1 survivors (pass/review). Stanford industry scorecard per SIC "
          f"code and Hamilton Helmer's 7 Powers per company, with TypeSafe Jev 1.14.")
    if args.dry_run:
        print("Dry run: no website fetched, no Jev call made.")
        return 0
    r = qualify.run(conn, cfg, eta, fetcher=fetcher, jev=jev, limit=args.limit, market=args.market)
    print(f"Industries scored {r['industries_scored']}; websites found {r['websites_found']}; 7 Powers decided "
          f"{r['powers_decided']}. Qualified {r['qualified']}, watch {r['watch']}, not qualified {r['not_qualified']}.")
    for i, q in enumerate(qualify.qualified(conn, cfg.slug)[:10], 1):
        b = q["breakdown"]
        print(f"  {i:>2}. {q['score']:>5} {q['verdict']:<9} {q['company_number']} {q['name'][:38]:<38} "
              f"industry {b.get('industry_score') or '?'}/30, powers {', '.join(b.get('clear_powers') or []) or '-'}")
    return 0


def cmd_us(args) -> int:
    """US: Form 5500 filings (current headcount, plan age, growth) + SBA PPP file -> sieve 1 (free)."""
    from gtm.eta import dol, us

    cfg, eta, conn = _setup(args)
    conf = eta.get("us") or {}
    years = [int(y) for y in conf.get("form5500_years") or []]
    ppp = us.cache_path()
    missing = [f"Form 5500 {y}" for y in years if not dol.csv_path(y, "sf").exists()] + \
              ([] if ppp.exists() else ["SBA PPP file"])
    if args.dry_run:
        print(f"Dry run: {len(conf.get('naics_codes') or {})} NAICS codes, Form 5500 years {years}, PPP file. "
              f"To download (free): {', '.join(missing) or 'nothing'}. Nothing written.")
        return 0
    for y in years:
        if not dol.csv_path(y, "sf").exists():
            print(f"Downloading Form 5500 plan year {y} (free, about 300 MB zipped)...")
            dol.download(y)
    if not ppp.exists():
        print("Downloading the SBA PPP file (about 450 MB, free, once)...")
        us.download(conf["ppp_url"], ppp)
    codes = {str(c) for c in conf.get("naics_codes") or {}}
    employers = dol.employers(years, codes) if years else {}
    # a full rebuild: US rows are derived from local files only, so they are replaced, not merged
    for table in ("eta_screen", "eta_evidence", "eta_owners", "eta_companies"):
        conn.execute(f"DELETE FROM {table} WHERE client=? AND company_number LIKE 'US-%'", (cfg.slug,))
    run_id = db.start_run(conn, cfg.slug, "eta_us", "dol+sba", "Form 5500 + PPP discovery and sieve 1", 0.0,
                          {"limit": args.limit, "years": years})
    r = us.run(conn, cfg.slug, eta, ppp, employers, limit=args.limit)
    db.finish_run(conn, run_id, "ok", r["kept"], 0.0, json.dumps(r)[:500])
    print(f"US: {r['form5500']} employers with a plan (Form 5500 {years[-1] if years else '-'}), {r['ppp']} PPP "
          f"borrowers, {r['both']} in both; {r['candidates']} candidates. Sieve 1: pass {r['pass']}, review "
          f"{r['review']}, fail {r['fail']}. Stored the best {r['kept']}.")
    if r["fails"]:
        print("  fail reasons: " + ", ".join(f"{k} {v}" for k, v in sorted(r["fails"].items(), key=lambda x: -x[1])))
    out = data_dir() / "eta" / f"us-shortlist-{date.today():%Y%m%d}.csv"
    rows = conn.execute("SELECT c.company_number, c.name, c.locality, c.postal_code, s.verdict, s.score, s.metrics"
                        " FROM eta_companies c JOIN eta_screen s ON s.client=c.client AND s.company_number=c.company_number"
                        " AND s.sieve=1 WHERE c.client=? AND c.company_number LIKE 'US-%' AND s.verdict IN"
                        " ('pass','review') ORDER BY s.score DESC", (cfg.slug,)).fetchall()
    cols = ["rank", "verdict", "score", "company_id", "name", "locality", "zip", "naics", "industry", "headcount",
            "headcount_source", "headcount_before", "plan_since", "revenue_est", "revenue_basis", "sources",
            "ppp_jobs", "second_draw", "business_age"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i, row in enumerate(rows, 1):
            m = json.loads(row["metrics"])
            w.writerow([i, row["verdict"], row["score"], row["company_number"], row["name"], row["locality"],
                        row["postal_code"], m.get("naics"), m.get("industry"), m.get("headcount"),
                        m.get("headcount_source"), m.get("active_before"), m.get("plan_since"), m.get("revenue_est"),
                        m.get("revenue_basis"), "+".join(m.get("sources") or []), m.get("ppp_jobs"),
                        m.get("second_draw"), m.get("business_age")])
    print(f"Shortlist: {len(rows)} US companies in {out}")
    return 0


def cmd_owners(args, fe=None) -> int:
    """US: who leads each shortlisted company, estimated age and tenure (FullEnrich people search, paid)."""
    from gtm.eta import owners_us

    cfg, _, conn = _setup(args)
    p = owners_us.plan(conn, cfg, args.limit, args.per_company)
    print(f"US owner lookup: {p['companies']} companies with a verified website and no lookup yet "
          f"(sieve 2 qualified or watch). Up to {args.per_company} people each: at most {p['max_people']} people, "
          f"{p['max_credits']:g} FullEnrich credits, about ${p['estimate_usd']:.2f} (only people returned are charged).")
    print(f"FullEnrich budget for {cfg.slug}: cap ${p['cap_usd'] or 0:.2f} a month, spent ${p['spent_usd']:.2f}.")
    if args.dry_run:
        for row in p["rows"][:5]:
            print(f"  {row['company_number']}  {row['name'][:40]:<40} {row['domain']}")
        if p["rows"]:
            print("First request (POST /people/search):")
            print(json.dumps(owners_us.search_body(p["rows"][0]["domain"], args.per_company), indent=2))
        need = p["estimate_usd"] - ((p["cap_usd"] or 0) - p["spent_usd"])
        if need > 0:
            print(f"A live run needs the monthly cap raised by at least ${need:.2f} (limits.yaml fullenrich). "
                  f"Nothing was called.")
        else:
            print("Dry run: nothing was called.")
        db.finish_run(conn, db.start_run(conn, cfg.slug, "eta_owners", "fullenrich", "US owner lookup (dry run)",
                                         p["estimate_usd"], {"limit": args.limit}), "dry_run", 0, 0.0, "")
        conn.commit()
        return 0
    if fe is None:
        from gtm.sources.fullenrich import FullEnrichClient
        fe = FullEnrichClient()
    r = owners_us.run(conn, cfg, fe, args.limit, args.per_company)
    print(f"Looked up {r['companies']} companies: people found at {r['with_people']}, {r['people']} people, "
          f"age estimated for {r['ages']}. {r['credits']:g} credits, ${r['cost_usd']:.2f}.")
    return 0


def cmd_pl(args, krs=None) -> int:
    """Poland: KRS daily bulletin -> current extracts -> target PKD companies -> sieve 1 (free)."""
    from gtm.eta import pl

    cfg, eta, conn = _setup(args)
    conf = eta.get("pl") or {}
    end = date.fromisoformat(args.until) if args.until else date.today() - timedelta(days=1)
    days = pl.days_back(end, args.days)
    print(f"Poland: KRS bulletin for {len(days)} working days ({days[-1]} to {days[0]}), "
          f"{len(conf.get('pkd_codes') or {})} PKD codes, {conf.get('requests_per_second', 2)} requests a second.")
    if args.dry_run:
        print("Dry run: nothing fetched.")
        return 0
    krs = krs or pl.KRSClient(conf.get("api", "https://api-krs.ms.gov.pl/api/krs"),
                              float(conf.get("requests_per_second", 2)), max_requests=args.max_requests)
    run_id = db.start_run(conn, cfg.slug, "eta_pl", "krs", "KRS discovery + sieve 1", 0.0,
                          {"days": days, "max_new": args.max_new})
    r = pl.run(conn, cfg.slug, eta, krs, days, max_new=args.max_new)
    db.finish_run(conn, run_id, "stopped" if r.get("stopped") else "ok", krs.requests_made, 0.0, json.dumps(r)[:500])
    print(f"Read {r['read']} extracts of {r['numbers']} new numbers; kept {r['kept']}. Sieve 1: pass {r['pass']}, "
          f"review {r['review']}, fail {r['fail']}.")
    if r["fails"]:
        print("  fail reasons: " + ", ".join(f"{k} {v}" for k, v in r["fails"].items()))
    if r.get("stopped"):
        print(f"Stopped: {r['stopped']}. Re-run later: numbers already read are not fetched again.")
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
    s.add_argument("--reparse", action="store_true", help="re-read cached filings with the current parser first")
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
    q.add_argument("--market", choices=["GB", "US", "PL"], help="only companies in this country")
    q.set_defaults(func=cmd_qualify)

    u = sub.add_parser("eta-us", help="ETA US: Form 5500 + SBA PPP files -> target NAICS employers -> sieve 1 (free)")
    u.add_argument("--limit", type=int, help="borrowers to keep this run (default us.max_per_run)")
    u.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    u.set_defaults(func=cmd_us)

    pp = sub.add_parser("eta-pl", help="ETA Poland: KRS bulletin -> target PKD companies -> sieve 1 (free)")
    pp.add_argument("--days", type=int, default=1, help="working days of the bulletin to read (default 1)")
    pp.add_argument("--until", help="last bulletin day, YYYY-MM-DD (default yesterday)")
    pp.add_argument("--max-new", type=int, help="extracts to read this run")
    pp.add_argument("--max-requests", type=int, default=20000, help="request cap for this run")
    pp.add_argument("--dry-run", action="store_true", help="show the plan, fetch nothing")
    pp.set_defaults(func=cmd_pl)

    ow = sub.add_parser("eta-owners", help="ETA US: owner, estimated age and tenure per shortlisted company "
                                           "(FullEnrich, paid; dry run first)")
    ow.add_argument("--limit", type=int, help="companies to look up")
    ow.add_argument("--per-company", type=int, default=3, help="people per company (default 3)")
    ow.add_argument("--dry-run", action="store_true", help="show companies, request and cost; call nothing")
    ow.set_defaults(func=cmd_owners)

    st = sub.add_parser("eta-stats", help="ETA: companies per stage, sieve verdicts, requests this month")
    st.set_defaults(func=cmd_stats)

    ev = sub.add_parser("eta-evidence", help="ETA: the evidence ledger for one company")
    ev.add_argument("company_number")
    ev.set_defaults(func=cmd_evidence)
