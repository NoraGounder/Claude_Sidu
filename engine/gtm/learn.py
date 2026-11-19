"""Outcome report: which signal, opening, process, tier, persona and region start conversations.

Counts only what Smartlead sync has recorded (outbound + replies), so it is free to run. A lead counts
as a conversation when its latest reply is interested, question or referral. Pancake's advice
(gtmbrain.si / pancake.ai) and ours: judge by conversations started per signal, not by emails sent,
then move effort to what works (scoring.yaml weights, hook_priority, brain.yaml hypotheses).
"""

from __future__ import annotations

import json
from collections import defaultdict

from gtm.config import ClientConfig

CONVERSATION = {"interested", "question", "referral"}
MEETING_HELD = {"held", "qualified", "follow_up", "not_a_fit", "proposal", "won", "lost"}   # as in l7_handoff
DIMENSIONS = ("signal", "hook", "process", "tier", "persona", "region")


def outcomes(cfg: ClientConfig, conn) -> dict[str, dict[str, dict[str, int]]]:
    rows = conn.execute(
        "SELECT o.contact_id, o.status, d.hook, d.process, c.persona, s.tier, s.breakdown, k.region,"
        " dl.stage AS deal_stage, dl.value_eur,"
        " (SELECT r.category FROM replies r WHERE r.client=o.client AND r.contact_id=o.contact_id"
        "  ORDER BY r.received_at DESC, r.id DESC LIMIT 1) AS category"
        " FROM outbound o JOIN drafts d ON d.id=o.draft_id JOIN contacts c ON c.id=o.contact_id"
        " JOIN campaigns k ON k.id=o.campaign_id LEFT JOIN l2_scores s ON s.account_id=o.account_id"
        " LEFT JOIN deals dl ON dl.contact_id=o.contact_id"
        " WHERE o.client=?", (cfg.slug,)).fetchall()
    report: dict[str, dict[str, dict[str, int]]] = {
        dim: defaultdict(lambda: {"contacted": 0, "replied": 0, "conversations": 0, "meetings": 0, "won": 0,
                                  "revenue_eur": 0.0, "unsubscribed": 0, "bounced": 0}) for dim in DIMENSIONS}
    for r in rows:
        signals = [k for k, pts in (json.loads(r["breakdown"] or "{}").get("signals") or {}).items() if pts]
        keys = {"signal": signals or ["none"], "hook": [r["hook"]], "process": [r["process"]],
                "tier": [r["tier"] or "unknown"], "persona": [r["persona"] or "unknown"], "region": [r["region"]]}
        for dim, values in keys.items():
            for value in values:
                cell = report[dim][value]
                cell["contacted"] += 1
                cell["replied"] += int(r["category"] is not None and r["category"] != "out_of_office")
                cell["conversations"] += int(r["category"] in CONVERSATION)
                cell["unsubscribed"] += int(r["status"] == "unsubscribed" or r["category"] == "unsubscribe")
                cell["bounced"] += int(r["status"] == "bounced")
                cell["meetings"] += int(r["deal_stage"] in MEETING_HELD)
                if r["deal_stage"] == "won":
                    cell["won"] += 1
                    cell["revenue_eur"] += r["value_eur"] or 0.0
    return {dim: dict(v) for dim, v in report.items()}


def format_report(report: dict, min_contacted: int = 1) -> list[str]:
    lines = []
    for dim in DIMENSIONS:
        cells = {k: v for k, v in report.get(dim, {}).items() if v["contacted"] >= min_contacted}
        if not cells:
            continue
        lines.append(f"By {dim}:")
        for key, v in sorted(cells.items(), key=lambda kv: (-kv[1]["conversations"] / kv[1]["contacted"], kv[0])):
            rate = 100 * v["conversations"] / v["contacted"]
            lines.append(f"  {key}: {v['contacted']} contacted, {v['replied']} replied, "
                         f"{v['conversations']} conversations ({rate:.1f}%), {v['meetings']} meetings, "
                         f"{v['won']} won (EUR {v['revenue_eur']:,.0f}), {v['unsubscribed']} unsubscribed, "
                         f"{v['bounced']} bounced")
    return lines or ["No outbound leads synced yet."]
