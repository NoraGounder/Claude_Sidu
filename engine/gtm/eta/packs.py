"""One-page deal packs: everything the search knows about a qualified company, for Sidarth's yes or no.

Each pack is a Markdown page in data/eta/packs/ (gitignored: it names people). It holds the snapshot, the size
evidence and how sure we are of it, the leader, the Stanford industry scorecard, the 7 Powers with the question
to test each one, the evidence ledger, red flags, and the questions for a first call. index.md ranks them.
Nothing here calls a paid service: it reads the tables the sieves and lookups already filled.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from gtm.config import data_dir
from gtm.eta import markets, store

POWER_QUESTIONS = {
    "scale_economies": "Does your cost per job fall as you do more work in the same area or for the same customers?",
    "network_economies": "Does the service get more valuable to each customer as you add customers?",
    "counter_positioning": "Is there something you do that bigger competitors could copy only by hurting their own business?",
    "switching_costs": "What would a customer lose (time, certification, re-training, risk) by moving to another supplier?",
    "branding": "Do customers pay you more than a competitor for the same work, and why?",
    "cornered_resource": "Which licences, certifications, contracts or people do you have that others cannot get?",
    "process_power": "What do you do differently that competitors have tried and failed to copy?",
}
FIRST_CALL = [
    "Is the business for sale now, or in the next one to three years? Who else is involved in that decision?",
    "Three years of revenue, gross margin and EBITDA (owner add-backs separately).",
    "Top 10 customers' share of revenue; how much is recurring (service contracts, maintenance, repeat clients)?",
    "Who runs day-to-day work if the owner steps back? Who are the key people and how long have they stayed?",
    "Owner's own role: what would a new owner need to take over in the first year?",
    "Real estate, equipment and working capital: owned or leased, and what comes with the business?",
]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def folder() -> Path:
    path = data_dir() / "eta" / "packs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _money(v) -> str:
    return "unknown" if v in (None, "") else f"${float(v) / 1e6:,.1f}M"


def gather(conn, client: str, number: str, eta: dict) -> dict:
    row = conn.execute("SELECT * FROM eta_companies WHERE client=? AND company_number=?", (client, number)).fetchone()
    s1 = conn.execute("SELECT * FROM eta_screen WHERE client=? AND company_number=? AND sieve=1",
                      (client, number)).fetchone()
    s2 = conn.execute("SELECT * FROM eta_screen WHERE client=? AND company_number=? AND sieve=2",
                      (client, number)).fetchone()
    key = markets.industry_key(number, row["search_code"])
    ind = conn.execute("SELECT * FROM eta_industry WHERE client=? AND sic_code=?", (client, key)).fetchone()
    site = conn.execute("SELECT website FROM eta_websites WHERE client=? AND company_number=?",
                        (client, number)).fetchone()
    return {"row": dict(row), "m": json.loads(s1["metrics"]), "s1": dict(s1), "s2": dict(s2) if s2 else None,
            "b2": json.loads(s2["breakdown"]) if s2 else {}, "industry": dict(ind) if ind else None,
            "industry_label": markets.code_labels(eta).get(key, row["search_code"]),
            "website": site["website"] if site else None,
            "owners": [dict(o) for o in store.owners(conn, client, number)],
            "ledger": [dict(e) for e in store.evidence(conn, client, number)]}


def red_flags(d: dict, today: date) -> list[str]:
    m, flags = d["m"], []
    if m.get("second_draw"):
        flags.append("Took a second PPP loan, which required a 25% revenue fall in a 2020 quarter.")
    before, now = m.get("active_before"), m.get("headcount")
    if before and now and now < before * 0.9:
        flags.append(f"Headcount fell from {before} to {now} between {m['years_compared'][0]} and {m['years_compared'][1]}.")
    ledger = {e["claim"]: e for e in d["ledger"]}
    since = (ledger.get("Leader since") or {}).get("value")
    if since and since.isdigit() and today.year - int(since) <= 4:
        flags.append(f"The current leader took over in {since}: succession may already be settled.")
    if (ledger.get("Owner or CEO found") or {}).get("value") in ("no", "no people", None):
        flags.append("No owner, president or CEO found online: ownership and age unknown.")
    if "ppp" not in (m.get("sources") or []):
        flags.append("No PPP loan matched: revenue rests on the industry average only.")
    return flags


def render(d: dict, eta: dict, rank: int, today: date) -> str:
    row, m, b2 = d["row"], d["m"], d["b2"]
    band = float((eta.get("us") or {}).get("revenue_band", 0.3))
    rev = m.get("revenue_est")
    ledger = {e["claim"]: e for e in d["ledger"]}
    leader = ledger.get("Owner or CEO found", {}).get("value")
    age = ledger.get("Owner age (estimate)", {}).get("value")
    since = ledger.get("Leader since", {}).get("value")
    signer = next((o["name"] for o in d["owners"] if (o["role"] or "").startswith("signed the")), None)
    named = next((o for o in d["owners"] if (o["source"] or "").startswith("fullenrich")
                  and o["role"] == leader), None) if leader and leader not in ("no", "no people") else None
    L = []
    L.append(f"# {rank}. {row['name']}")
    L.append("")
    L.append(f"{row['locality']} · {d['industry_label']} (NAICS {row['search_code']}) · "
             f"{d['website'] or 'website not verified'} · id {row['company_number']}")
    L.append("")
    L.append(f"**Sieve 2: {d['s2']['verdict'] if d['s2'] else '-'} ({d['s2']['score'] if d['s2'] else '-'})** · "
             f"sieve 1 {d['s1']['verdict']} ({d['s1']['score']}) · built {today.isoformat()}")
    L.append("")
    L.append("## Snapshot")
    L.append("")
    L.append("| | Value | How sure |")
    L.append("|---|---|---|")
    hc = f"{m.get('headcount')} active plan participants ({m.get('headcount_source')})"
    if m.get("active_before"):
        hc += f", {m['active_before']} in {m['years_compared'][0]}"
    L.append(f"| Headcount | {hc} | public filing |")
    if m.get("ppp_jobs"):
        L.append(f"| Jobs (PPP 2020-21) | {m['ppp_jobs']} | public filing |")
    L.append(f"| Revenue | {_money(rev * (1 - band))} - {_money(rev * (1 + band))} | estimate: {m.get('revenue_basis')} |"
             if rev else "| Revenue | unknown | |")
    L.append(f"| In business since | retirement plan since {m.get('plan_since') or 'unknown'} | floor on company age |")
    L.append(f"| Leader | {leader or 'not looked up'}{', ' + named['name'] if named else ''} | work history online |")
    L.append(f"| Leader age | {age or 'unknown'} | estimate from degree or first job dates |")
    L.append(f"| Leading since | {since or 'unknown'} | work history online |")
    if signer:
        L.append(f"| Signed the plan filing | {signer} | public filing (often the owner or president) |")
    L.append(f"| EBITDA, margins, customers | unknown | ask the owner |")
    L.append("")
    L.append("## Why it is on the list")
    L.append("")
    br = json.loads(d["s1"]["breakdown"])
    L.append("Sieve 1 points: " + ", ".join(f"{k.replace('_', ' ')} {v:g}" for k, v in br.items()) + ".")
    if d["industry"]:
        crit = (eta.get("industry_scorecard") or {}).get("criteria") or {}
        ans = json.loads(d["industry"]["answers"])
        L.append("")
        L.append(f"Stanford industry scorecard: **{d['industry']['score']:g} of 30** "
                 f"(bar {(eta.get('industry_scorecard') or {}).get('min_score')}). Weakest: "
                 + ", ".join(f"{crit.get(k, k).split(':')[0].lower()} {v:g}"
                             for k, v in sorted(ans.items(), key=lambda x: x[1])[:3]) + ".")
    L.append("")
    L.append("## 7 Powers to test (website evidence only)")
    L.append("")
    scores = b2.get("power_scores") or {}
    shown = [(k, v) for k, v in sorted(scores.items(), key=lambda x: -x[1]) if v >= 0.5]
    if not shown:
        L.append("No Power visible on the website. Ask the owner what competitors cannot copy.")
    for k, v in shown:
        level = "clear" if v >= 1.5 else "some" if v >= 1.0 else "faint"
        L.append(f"- **{k.replace('_', ' ').capitalize()}** ({level}, {v:g}/2): {POWER_QUESTIONS.get(k, '')}")
    flags = red_flags(d, today)
    L.append("")
    L.append("## Red flags and gaps")
    L.append("")
    L.extend(f"- {f}" for f in flags) if flags else L.append("- None seen in public data.")
    L.append("")
    L.append("## First call")
    L.append("")
    L.extend(f"{i}. {q}" for i, q in enumerate(FIRST_CALL, 1))
    L.append("")
    L.append("## Evidence ledger")
    L.append("")
    L.append("| Claim | Value | Status | Next step |")
    L.append("|---|---|---|---|")
    estimated = bool((ledger.get("Owner age (estimate)") or {}).get("value"))
    for e in d["ledger"]:
        if e["claim"] == "Owner age" and estimated:
            continue                      # the estimate row below replaces the placeholder
        L.append(f"| {e['claim']} | {e['value'] or '-'} | {e['status']} | {e.get('next_step') or ''} |".replace("\n", " "))
    L.append("")
    L.append("Your call: **yes** (start outreach), **no**, or **more** (what to find out first).")
    return "\n".join(L) + "\n"


def build(conn, client: str, eta: dict, market: str | None = "US", verdicts=("qualified",),
          today: date | None = None) -> dict:
    today = today or date.today()
    marks = ",".join("?" for _ in verdicts)
    rows = conn.execute(f"SELECT company_number FROM eta_screen WHERE client=? AND sieve=2 AND verdict IN ({marks})"
                        f" ORDER BY score DESC", (client, *verdicts)).fetchall()
    numbers = [r["company_number"] for r in rows
               if not market or markets.market_of(r["company_number"]) == market]
    out_dir = folder()
    for old in out_dir.glob("*.md"):
        old.unlink()
    index = [f"# Deal packs ({market or 'all markets'}), {today.isoformat()}", "",
             f"{len(numbers)} companies, best first. Each page ends with your call: yes, no or more.", "",
             "| # | Company | Where | Industry | Staff | Revenue (est.) | Leader | Age | Since | Flags |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    numbers = [n for n in numbers if conn.execute("SELECT 1 FROM eta_screen WHERE client=? AND company_number=?"
                                                 " AND sieve=1", (client, n)).fetchone()]
    for rank, number in enumerate(numbers, 1):
        d = gather(conn, client, number, eta)
        name = f"{rank:03d}-{_slug(d['row']['name'])}.md"
        (out_dir / name).write_text(render(d, eta, rank, today), encoding="utf-8")
        led = {e["claim"]: e["value"] for e in d["ledger"]}
        index.append(f"| {rank} | [{d['row']['name']}]({name}) | {d['row']['locality']} | {d['industry_label']} | "
                     f"{d['m'].get('headcount')} | {_money(d['m'].get('revenue_est'))} | "
                     f"{led.get('Owner or CEO found') or '-'} | {led.get('Owner age (estimate)') or '-'} | "
                     f"{led.get('Leader since') or '-'} | {len(red_flags(d, today))} |")
    (out_dir / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return {"packs": len(numbers), "folder": str(out_dir)}
