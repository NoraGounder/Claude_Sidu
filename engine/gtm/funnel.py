"""Funnel and cost report for one client: from companies found to customers won, with what each step
cost. Free to run (local data only). Counts are per client, so Quailworks' own campaign never mixes
with a client's.
"""

from __future__ import annotations

from gtm.config import ClientConfig

POSITIVE = ("interested", "question", "referral")
HELD = ("held", "qualified", "follow_up", "not_a_fit", "proposal", "won", "lost")


def report(cfg: ClientConfig, conn) -> dict:
    one = lambda sql, *a: conn.execute(sql, (cfg.slug, *a)).fetchone()[0] or 0  # noqa: E731
    steps = {
        "companies found": one("SELECT COUNT(*) FROM accounts WHERE client=?"),
        "passed first filters": one("SELECT COUNT(*) FROM accounts WHERE client=? AND status != 'rejected_l1'"),
        "qualified companies (Tier 1-2)": one("SELECT COUNT(*) FROM accounts WHERE client=? AND status IN ('tier_1','tier_2')"),
        "buyers selected": one("SELECT COUNT(*) FROM contacts c JOIN accounts a ON a.id=c.account_id WHERE c.client=?"
                               " AND a.status IN ('tier_1','tier_2') AND c.status NOT IN ('candidate','skipped')"),
        "work emails found": one("SELECT COUNT(*) FROM contacts c JOIN accounts a ON a.id=c.account_id WHERE c.client=?"
                                 " AND a.status IN ('tier_1','tier_2') AND c.email IS NOT NULL AND c.email != ''"),
        "usable (verified, passed the gate)": one(
            "SELECT COUNT(*) FROM contacts c JOIN accounts a ON a.id=c.account_id WHERE c.client=?"
            " AND a.status IN ('tier_1','tier_2') AND (c.status='ready' OR (c.status='held'"
            " AND c.status_reason='sender_consent_pending'))"),
        "emailed": one("SELECT COUNT(DISTINCT contact_id) FROM outbound WHERE client=?"),
        "positive replies": one("SELECT COUNT(DISTINCT contact_id) FROM replies WHERE client=? AND category IN (?,?,?)", *POSITIVE),
        "meetings held": one(f"SELECT COUNT(*) FROM deals WHERE client=? AND stage IN ({','.join('?' * len(HELD))})", *HELD),
        "customers won": one("SELECT COUNT(*) FROM deals WHERE client=? AND stage='won'"),
    }
    spend = {r[0]: round(r[1], 2) for r in conn.execute(
        "SELECT vendor, SUM(COALESCE(actual_cost, 0)) FROM runs WHERE client=? AND status != 'dry_run'"
        " GROUP BY vendor ORDER BY vendor", (cfg.slug,))}
    total = round(sum(spend.values()), 2)
    per = {k: round(total / v, 2) for k, v in steps.items() if v and k in (
        "qualified companies (Tier 1-2)", "usable (verified, passed the gate)", "positive replies",
        "meetings held", "customers won")}
    return {"steps": steps, "spend": spend, "total": total, "cost_per": per}


def format_report(cfg: ClientConfig, r: dict) -> list[str]:
    lines = [f"Funnel for {cfg.slug} (all time, this client only)"]
    lines += [f"  {k:38} {v:>6}" for k, v in r["steps"].items()]
    lines.append(f"Data and AI spend: ${r['total']:.2f} (" + ", ".join(f"{k} ${v:.2f}" for k, v in r["spend"].items() if v) + ")")
    lines += [f"  cost per {k}: ${v:.2f}" for k, v in r["cost_per"].items()]
    lines.append("Not counted: subscriptions (Smartlead, mailboxes, domains, Apify plan) and your time.")
    return lines
