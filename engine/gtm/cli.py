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
          f"Unreachable sites {summary['unreachable']}; with Jev 1.14 decisions {summary['jev_decided']}.")
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


def cmd_jev(args) -> int:
    """Layer 2 AI decisions with TypeSafe Jev 1.14 only (see clients/<client>/ai.yaml)."""
    from gtm.layers import l2_jev
    from gtm.sources.jev import JevPolicyError, JevUnavailable

    cfg = load_client(args.client)
    conn = db.connect()
    if args.purge_legacy:
        counts = l2_jev.purge_legacy_ai(conn, cfg.slug)
        print(f"Removed pre-policy AI verdicts: {counts['evidence_removed']} evidence rows, "
              f"{counts['drops_undone']} drops undone. Re-score with: prefilter --rescore")
        return 0
    try:
        jp = l2_jev.plan(cfg, conn, limit=args.limit, redo=args.redo)
    except JevPolicyError as exc:
        print(f"Refused by the AI policy: {exc}")
        return 3
    print(f"Jev decisions with {jp.model}: {len(jp.items)} accounts, estimated ${jp.est_cost:.4f}")
    if args.dry_run:
        if jp.items:
            state, questions, _ = l2_jev.build_request(cfg, jp.items[0])
            print("First request (state and questions):")
            print(json.dumps({"state": state, "questions": list(questions)}, ensure_ascii=False, indent=1)[:2500])
        print("Dry run: nothing was called or spent.")
        return 0
    if not jp.items:
        return 0
    try:
        t = l2_jev.run(cfg, conn, jp)
    except (JevUnavailable, JevPolicyError) as exc:
        print(f"Stopped: {exc}")
        print("No other model was used. Fix the cause and run the same command again; decided accounts are kept.")
        return 4
    except budget.BudgetExceeded as exc:
        print(f"Stopped: {exc}")
        return 2
    r = t.get("rescored", {})
    print(f"Jev decided {t['decided']} accounts. Model IDs reported: {', '.join(t['models'])}. "
          f"Tokens in/out: {t['input_tokens']}/{t['output_tokens']}. Cost ${t['cost_usd']:.6f}.")
    if r:
        print(f"Re-scored: Tier 1 {r['tier_1']}, Tier 2 {r['tier_2']}, Tier 3 {r['tier_3']}, dropped {r['rejected_l2']}.")
    return 0


def cmd_contacts(args) -> int:
    """Layer 3: decision-makers and work emails (FullEnrich), ranked by Jev 1.14."""
    from gtm.layers import l3_contacts
    from gtm.sources.fullenrich import FullEnrichError
    from gtm.sources.jev import JevPolicyError, JevUnavailable

    cfg = load_client(args.client)
    conn = db.connect()
    cp = l3_contacts.plan(cfg, conn, limit=args.limit, search_limit=args.search_limit)
    selected = conn.execute("SELECT COUNT(*) FROM contacts WHERE client=? AND status='selected'",
                            (cfg.slug,)).fetchone()[0]
    print(f"Layer 3 plan: people search for {len(cp.accounts)} accounts (up to {cp.search_limit} people each), "
          f"estimated ${cp.est_search_cost:.2f}; {selected} selected contacts already waiting for an email.")
    if args.dry_run:
        for acc in cp.accounts[:10]:
            print(f"  - [{acc['tier']}] {acc['name']} ({acc['domain']}) fit {acc['fit']} signal {acc['signal']}")
        print("Dry run: nothing was called or spent.")
        return 0
    try:
        if not args.emails_only and cp.accounts:
            t = l3_contacts.find_people(cfg, conn, cp)
            print(f"People search: {t['accounts']} accounts, {t['people_returned']} people returned, "
                  f"{t['candidates']} passed the checks, {t['selected']} selected. Cost ${t['cost_usd']:.2f}.")
        if not args.skip_emails:
            e = l3_contacts.find_emails(cfg, conn, limit=args.limit)
            print(f"Work emails: {e['requested']} requested, {e['found']} found, {e['catch_all']} catch-all, "
                  f"{e['not_found']} not found. Cost ${e['cost_usd']:.2f}.")
    except (JevUnavailable, JevPolicyError) as exc:
        print(f"Stopped by Jev: {exc}. No other model was used; run again to continue.")
        return 4
    except budget.BudgetExceeded as exc:
        print(f"Stopped: {exc}")
        return 2
    except FullEnrichError as exc:
        print(f"Stopped by FullEnrich: {exc}")
        return 5
    return 0


def cmd_gate(args) -> int:
    """Layer 4: send gate (deterministic)."""
    from gtm.layers import l4_gate
    from gtm.sources.millionverifier import MillionVerifierError

    cfg = load_client(args.client)
    conn = db.connect()
    try:
        res = l4_gate.run(cfg, conn, recheck=args.recheck)
    except MillionVerifierError as exc:
        print(f"Stopped: {exc}")
        return 5
    except budget.BudgetExceeded as exc:
        print(f"Stopped: {exc}")
        return 2
    counts = ", ".join(f"{k} {v}" for k, v in sorted(res.counts.items())) or "no contacts with an email"
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(res.reasons.items())) or "none"
    print(f"Layer 4 gate: {counts}. Reasons: {reasons}.")
    return 0


def cmd_draft(args) -> int:
    """Layer 5: fact-based drafts from approved templates; Jev 1.14 picks the angle and fact-checks."""
    from gtm.layers import l5_copy
    from gtm.sources.jev import JevPolicyError, JevUnavailable

    cfg = load_client(args.client)
    conn = db.connect()
    try:
        t = l5_copy.draft(cfg, conn, redo=args.redo, limit=args.limit)
    except (JevUnavailable, JevPolicyError) as exc:
        print(f"Stopped by Jev: {exc}. No other model was used; run again to continue.")
        return 4
    hooks = ", ".join(f"{k} {v}" for k, v in sorted(t["hooks"].items())) or "none"
    print(f"Drafted {t['drafted']} contacts ({t['preview']} preview only, {t['needs_review']} flagged by "
          f"Jev's fact check). Openings used: {hooks}.")
    if t["preview"]:
        print("Preview only: add clients/<client>/private/sender.yaml (see sender.example.yaml) and re-draft.")
    return 0


def cmd_export_drafts(args) -> int:
    from gtm.layers import l5_copy

    cfg = load_client(args.client)
    path, n = l5_copy.export_review(cfg, db.connect(), args.out)
    print(f"Wrote {n} drafts to {path}. Import it into Google Sheets, set decision to approve or reject, "
          f"then download as CSV and run import-review. Delete the sheet afterwards (personal data).")
    return 0


def cmd_import_review(args) -> int:
    from gtm.layers import l5_copy

    cfg = load_client(args.client)
    c = l5_copy.import_review(cfg, db.connect(), args.file)
    print(f"Approved {c['approved']}, rejected {c['rejected']}, unchanged {c['unchanged']}.")
    for err in c["errors"]:
        print(f"  not approved: {err}")
    return 0 if not c["errors"] else 6


def cmd_push(args) -> int:
    """Layer 6: upload eligible leads to Smartlead. Campaigns are not started."""
    from gtm.layers import l6_send
    from gtm.sources.smartlead import SmartleadError

    cfg = load_client(args.client)
    conn = db.connect()
    plan = l6_send.plan_push(cfg, conn)
    eligible = sum(len(v) for v in plan.eligible.values())
    regions = ", ".join(f"{k} {len(v)}" for k, v in plan.eligible.items()) or "none"
    held = ", ".join(f"{k} {v}" for k, v in sorted(plan.held.items())) or "none"
    print(f"Layer 6 plan: {eligible} leads eligible ({regions}). Held: {held}.")
    if not args.live:
        print("Dry run: nothing uploaded. Add --live to upload (campaigns stay paused until `start`).")
        return 0
    try:
        t = l6_send.push(cfg, conn, plan=plan)
    except (SmartleadError, RuntimeError) as exc:
        print(f"Stopped: {exc}")
        return 5
    print(f"Uploaded {t['pushed']} leads to campaigns {t['campaigns']}. Nothing is sending yet.")
    for p in t.get("mailbox_problems", []):
        print(f"  mailbox not linked: {p}")
    print("Check each campaign in Smartlead (sequence, settings, mailboxes), then start it with:"
          " python -m gtm --client <client> start --region <region> --i-confirm")
    return 0


def cmd_start(args) -> int:
    """Layer 6: the only command that makes Smartlead send."""
    from gtm.layers import l6_send
    from gtm.sources.smartlead import SmartleadError

    if not args.i_confirm:
        print("Refused: starting a campaign sends real emails. Re-run with --i-confirm after approval.")
        return 7
    cfg = load_client(args.client)
    try:
        name = l6_send.start(cfg, db.connect(), args.region)
    except (SmartleadError, RuntimeError) as exc:
        print(f"Stopped: {exc}")
        return 5
    print(f"Campaign '{name}' is ACTIVE. Smartlead now sends on its schedule.")
    return 0


def cmd_sync(args) -> int:
    """Layer 6: pull replies, bounces and unsubscribes; Jev 1.14 classifies replies."""
    from gtm.layers import l6_send
    from gtm.sources.jev import JevPolicyError, JevUnavailable
    from gtm.sources.smartlead import SmartleadError

    cfg = load_client(args.client)
    try:
        t = l6_send.sync(cfg, db.connect())
    except (JevUnavailable, JevPolicyError) as exc:
        print(f"Stopped by Jev: {exc}. No other model was used.")
        return 4
    except SmartleadError as exc:
        print(f"Stopped: {exc}")
        return 5
    cats = ", ".join(f"{k} {v}" for k, v in sorted(t["categories"].items())) or "none"
    print(f"Sync: {t['replies']} new replies ({cats}); {t['needs_human']} need a human reply now; "
          f"{t['bounced']} bounced and {t['unsubscribed']} unsubscribed (all suppressed).")
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


def cmd_learn(args) -> int:
    from gtm import learn

    cfg = load_client(args.client)
    conn = db.connect()
    for line in learn.format_report(learn.outcomes(cfg, conn), args.min_contacted):
        print(line)
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

    j = sub.add_parser("jev", help="Layer 2 AI decisions with TypeSafe Jev 1.14 (no other model)")
    j.add_argument("--limit", type=int)
    j.add_argument("--redo", action="store_true", help="decide again accounts Jev already decided")
    j.add_argument("--dry-run", action="store_true", help="show the first request and cost, call nothing")
    j.add_argument("--purge-legacy", action="store_true",
                   help="remove AI verdicts made before the Jev 1.14 policy (Jev Router)")
    j.set_defaults(func=cmd_jev)

    c = sub.add_parser("contacts", help="Layer 3: decision-makers and work emails (FullEnrich + Jev 1.14)")
    c.add_argument("--limit", type=int, help="only the first N accounts / contacts")
    c.add_argument("--search-limit", type=int, default=4, help="people returned per account (0.25 credit each)")
    c.add_argument("--emails-only", action="store_true", help="skip people search; find emails for selected contacts")
    c.add_argument("--skip-emails", action="store_true", help="people search and selection only")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_contacts)

    g = sub.add_parser("gate", help="Layer 4: send gate (suppression, email quality, consent, GDPR)")
    g.add_argument("--recheck", action="store_true", help="re-check stale emails with MillionVerifier first")
    g.set_defaults(func=cmd_gate)

    dr = sub.add_parser("draft", help="Layer 5: write fact-based email drafts (templates + Jev 1.14 checks)")
    dr.add_argument("--limit", type=int)
    dr.add_argument("--redo", action="store_true", help="re-draft contacts that already have a draft")
    dr.set_defaults(func=cmd_draft)

    ex = sub.add_parser("export-drafts", help="Layer 5: CSV of drafts for review in Google Sheets")
    ex.add_argument("--out")
    ex.set_defaults(func=cmd_export_drafts)

    ir = sub.add_parser("import-review", help="Layer 5: apply approve/reject decisions and edits from the CSV")
    ir.add_argument("--file", required=True)
    ir.set_defaults(func=cmd_import_review)

    pu = sub.add_parser("push", help="Layer 6: upload eligible leads to Smartlead (dry run unless --live)")
    pu.add_argument("--live", action="store_true")
    pu.set_defaults(func=cmd_push)

    st = sub.add_parser("start", help="Layer 6: start a Smartlead campaign (sends real emails)")
    st.add_argument("--region", required=True, help="region from sending.yaml, e.g. nl, uk_ie, us")
    st.add_argument("--i-confirm", action="store_true", help="required: confirms sending was approved")
    st.set_defaults(func=cmd_start)

    sy = sub.add_parser("sync", help="Layer 6: pull replies, bounces, unsubscribes; classify replies")
    sy.set_defaults(func=cmd_sync)

    le = sub.add_parser("learn", help="conversations started per signal, opening, tier, persona, region (free)")
    le.add_argument("--min-contacted", type=int, default=1, help="hide groups with fewer contacted leads")
    le.set_defaults(func=cmd_learn)

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
