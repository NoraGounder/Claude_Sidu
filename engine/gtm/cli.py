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
    plans = l1_discover.plan(cfg, args.segment, args.max_items, args.mode)
    if not plans:
        print("No enabled segments. Enable one in icp.yaml or pass --segment.")
        return 1

    conn = db.connect()
    total = sum(p.est_cost for p in plans)
    print(f"Layer 1 plan for {cfg.slug}: {len(plans)} search(es), up to "
          f"{sum(p.max_items for p in plans)} companies, estimated ${total:.2f}")
    for p in plans:
        print(f"  - {p.segment.name}: up to {p.max_items} companies, est. ${p.est_cost:.2f}")
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
    d.add_argument("--mode", choices=["short", "full"], default="short",
                   help="Harvest scraper mode; 'full' adds detail at a higher price")
    d.add_argument("--dry-run", action="store_true", help="show searches and cost, call nothing")
    d.add_argument("--fixture", help="read saved actor output from a JSON file instead of Apify")
    d.add_argument("--verbose", action="store_true")
    d.set_defaults(func=cmd_discover)

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
