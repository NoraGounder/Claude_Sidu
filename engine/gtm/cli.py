"""Command line for the lead engine. Claude Code (or a person) runs layers from here."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from gtm import budget, db
from gtm.config import data_dir, load_client
from gtm.layers import l1_discover


def cmd_discover(args) -> int:
    cfg = load_client(args.client)
    conn = db.connect()
    plans = l1_discover.plan(cfg, args.segment, args.max_items, args.mode, conn=conn)
    for name in l1_discover.exhausted_segments(cfg, conn):
        print(f"Segment {name} has used all 20 LinkedIn search pages. Split it (for example by "
              f"size band or region) in icp.yaml to find more companies.")
    if not plans:
        print("Nothing to run: no enabled segments with pages left.")
        return 1

    total = sum(p.est_cost for p in plans)
    print(f"Layer 1 plan for {cfg.slug}: {len(plans)} search(es), up to "
          f"{sum(p.max_items for p in plans)} companies, estimated ${total:.2f}")
    for p in plans:
        print(f"  - {p.segment.name}: pages {p.start_page}-{p.start_page + p.pages - 1}, "
              f"up to {p.max_items} companies, est. ${p.est_cost:.2f}")
        if args.verbose or args.dry_run:
            print("    input:", json.dumps(p.actor_input, ensure_ascii=False))

    if args.dry_run:
        try:
            info = budget.check(conn, cfg, l1_discover.VENDOR, total)
            print(f"Budget OK: ${info['remaining']:.2f} of ${info['cap']:.2f} left this month for apify.")
        except budget.BudgetExceeded as exc:
            print(f"Budget warning: {exc}")
        print("Dry run: nothing was called or spent.")
        return 0

    try:
        results = l1_discover.run(cfg, conn, plans, fixture=args.fixture)
    except budget.BudgetExceeded as exc:
        print(f"Stopped: {exc}")
        return 2

    for r in results:
        rejected = ", ".join(f"{k} {v}" for k, v in sorted(r.rejected.items())) or "none"
        cost = f"${r.cost_usd:.3f}" if r.cost_usd is not None else "unknown"
        print(f"{r.segment}: fetched {r.fetched}, new {r.new}, duplicates {r.duplicates}, "
              f"qualified {r.qualified}, rejected: {rejected}. Cost {cost}.")
    return 0


def cmd_prefilter(args) -> int:
    from gtm.layers import l2_prefilter

    cfg = load_client(args.client)
    conn = db.connect()
    print(f"Layer 2 for {cfg.slug}: crawling and scoring (free, uses time only)...")
    summary = l2_prefilter.run(cfg, conn, limit=args.limit, rescore=args.rescore, workers=args.workers)
    print(f"Scored {summary['accounts']} accounts: Tier 1 {summary['tier_1']}, Tier 2 {summary['tier_2']}, "
          f"Tier 3 {summary['tier_3']}, dropped {summary['rejected_l2']}. "
          f"Unreachable sites {summary['unreachable']}; job titles to review {summary['review_job_titles']}.")
    return 0


def cmd_tiers(args) -> int:
    cfg = load_client(args.client)
    conn = db.connect()
    rows = conn.execute(
        "SELECT a.id, a.name, a.domain, s.tier, s.fit, s.signal, s.flags, s.job_titles FROM accounts a"
        " JOIN l2_scores s ON s.account_id=a.id WHERE a.client=? AND s.tier=?"
        " ORDER BY s.signal DESC, s.fit DESC LIMIT ?", (cfg.slug, args.tier, args.top)).fetchall()
    for r in rows:
        ev = conn.execute("SELECT signal, label, url FROM evidence WHERE account_id=?", (r["id"],)).fetchall()
        labels = "; ".join(f"{e['label']}" for e in ev) or "no signals"
        print(f"[{r['tier']}] {r['name']} ({r['domain']}) fit {r['fit']} signal {r['signal']} | {labels}")
        if args.verbose:
            for e in ev:
                print(f"      {e['signal']}: {e['label']} <{e['url']}>")
    return 0


def cmd_review_queue(args) -> int:
    """Write accounts for the AI review (job titles, non-buyers) to JSONL in data/."""
    from gtm.layers import l2_prefilter

    cfg = load_client(args.client)
    conn = db.connect()
    out = args.out or str(data_dir() / f"{cfg.slug}-review-queue.jsonl")
    items = l2_prefilter.review_items(conn, cfg.slug, include_all=args.all)
    with open(out, "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Wrote {len(items)} accounts to {out}")
    return 0


def cmd_apply_review(args) -> int:
    from gtm.layers import l2_prefilter

    cfg = load_client(args.client)
    conn = db.connect()
    with open(args.file, encoding="utf-8") as fh:
        reviews = [json.loads(line) for line in fh if line.strip()]
    counts = l2_prefilter.apply_review(cfg, conn, reviews, args.reviewer)
    print(f"Applied {counts['reviewed']} reviews: {counts['changed_tier']} changed tier, "
          f"{counts['dropped']} dropped as not a buyer, {counts['ignored_titles']} titles ignored "
          f"(not in the export).")
    return 0


def cmd_stats(args) -> int:
    cfg = load_client(args.client)
    conn = db.connect()
    print(f"Accounts for {cfg.slug}:")
    for row in conn.execute(
        "SELECT status, COUNT(*) n FROM accounts WHERE client=? GROUP BY status ORDER BY n DESC", (cfg.slug,)
    ):
        print(f"  {row['status']}: {row['n']}")
    print("Rejections in Layer 1:")
    for row in conn.execute(
        "SELECT status_reason, COUNT(*) n FROM accounts WHERE client=? AND status='rejected_l1'"
        " GROUP BY status_reason ORDER BY n DESC", (cfg.slug,)
    ):
        print(f"  {row['status_reason']}: {row['n']}")
    print("Spend this month:")
    for vendor in cfg.limits.month_budget_usd:
        spent = db.month_spend(conn, cfg.slug, vendor)
        print(f"  {vendor}: ${spent:.2f} of ${cfg.limits.month_budget_usd[vendor]:.2f}")
    return 0


def cmd_export(args) -> int:
    cfg = load_client(args.client)
    conn = db.connect()
    out = args.out or str(data_dir() / f"{cfg.slug}-{args.status}.csv")
    cols = ["name", "domain", "website", "country", "city", "industry", "employee_count",
            "employee_range", "linkedin_url", "segments", "status", "status_reason", "first_seen"]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM accounts WHERE client=? AND status=? ORDER BY name",
        (cfg.slug, args.status),
    ).fetchall()
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        writer.writerows([tuple(r) for r in rows])
    print(f"Wrote {len(rows)} accounts to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gtm", description="Quailworks lead engine")
    parser.add_argument("--client", required=True, help="client folder name, e.g. the-marble-jar")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="Layer 1: find target accounts")
    d.add_argument("--segment", action="append", help="segment name from icp.yaml (repeatable)")
    d.add_argument("--max-items", type=int, help="cap companies per segment (default: icp.yaml)")
    d.add_argument("--mode", choices=["short", "full"], default="full",
                   help="Harvest scraper mode. 'full' (default) includes website, size and HQ; "
                        "'short' is half the price but lacks them")
    d.add_argument("--dry-run", action="store_true", help="show searches and cost, call nothing")
    d.add_argument("--fixture", help="read saved actor output from a JSON file instead of Apify")
    d.add_argument("--verbose", action="store_true")
    d.set_defaults(func=cmd_discover)

    p = sub.add_parser("prefilter", help="Layer 2: crawl sites, find signals, score and tier")
    p.add_argument("--limit", type=int, help="only the first N unscored accounts (for testing)")
    p.add_argument("--rescore", action="store_true", help="re-score accounts already scored (uses the cache)")
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(func=cmd_prefilter)

    t = sub.add_parser("tiers", help="show the top accounts in a tier with their evidence")
    t.add_argument("--tier", default="tier_1", choices=["tier_1", "tier_2", "tier_3", "rejected_l2"])
    t.add_argument("--top", type=int, default=20)
    t.add_argument("--verbose", action="store_true")
    t.set_defaults(func=cmd_tiers)

    r = sub.add_parser("review-queue", help="export accounts for the AI review to JSONL")
    r.add_argument("--out")
    r.add_argument("--all", action="store_true", help="every scored account, not only flagged ones")
    r.set_defaults(func=cmd_review_queue)

    ar = sub.add_parser("apply-review", help="apply AI review verdicts from a JSONL file")
    ar.add_argument("--file", required=True)
    ar.add_argument("--reviewer", default="claude", help="who reviewed: claude or jev")
    ar.set_defaults(func=cmd_apply_review)

    s = sub.add_parser("stats", help="counts by status and spend this month")
    s.set_defaults(func=cmd_stats)

    e = sub.add_parser("export", help="write accounts with a given status to CSV in data/")
    e.add_argument("--status", default="qualified_l1")
    e.add_argument("--out")
    e.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
