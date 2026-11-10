"""Layer 7: handoff, CRM and learning.

1. `handoff`: every reply that needs a person (interested, question, referral) becomes a deal and a
   one-page meeting brief in data/briefs/ (local only), with the first answer Quailworks sends from the
   Smartlead inbox (templates/replies.yaml, written by people). "Not now" replies become deals at stage
   `later`. Every other reply is marked handled. Nothing is sent from here.
2. `outcome`: Quailworks records what happened, including the sender's one word after a call
   (qualified / not a fit / follow up), and later proposal, won (with value) or lost. A won company
   becomes a best client: excluded from outreach and used as a lookalike (gtm/best_clients.py), so the
   engine learns who buys without asking anyone.
3. `crm`: mirrors deals to HubSpot free (companies, contacts, deals). Dry run unless --live, because
   CRM writes need the user's approval (CLAUDE.md rule 3). Never deletes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from gtm import db
from gtm.config import ClientConfig, data_dir
from gtm.layers.l5_copy import load_sender
from gtm.layers.l6_send import NEEDS_HUMAN
from gtm.sources.hubspot import CONTACT_TO_COMPANY, DEAL_TO_COMPANY, DEAL_TO_CONTACT

STAGES = ("interested", "later", "booked", "held", "qualified", "follow_up", "not_a_fit", "no_show",
          "proposal", "won", "lost")
# The sender's one-word answers after a call (Mithun for The Marble Jar)
WORDS = {"qualified": "qualified", "not a fit": "not_a_fit", "not_a_fit": "not_a_fit",
         "follow up": "follow_up", "follow_up": "follow_up", "no show": "no_show"}
MEETING_HELD = {"held", "qualified", "follow_up", "not_a_fit", "proposal", "won", "lost"}
OPEN = {"interested", "later", "booked", "held", "qualified", "follow_up", "proposal"}
# Our stage -> HubSpot default sales pipeline stage
HUBSPOT_STAGE = {"interested": "appointmentscheduled", "booked": "appointmentscheduled",
                 "later": "appointmentscheduled", "held": "qualifiedtobuy", "qualified": "qualifiedtobuy",
                 "follow_up": "qualifiedtobuy", "proposal": "contractsent", "won": "closedwon",
                 "lost": "closedlost", "not_a_fit": "closedlost", "no_show": "closedlost"}


def _templates(cfg: ClientConfig) -> dict:
    path = Path(cfg.root) / "templates" / "replies.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def suggested_reply(cfg: ClientConfig, category: str, first_name: str) -> str:
    t = _templates(cfg)
    sender, _ = load_sender(cfg)
    link = str(sender.get("booking_link") or "")
    real_link = link if link and "<" not in link else ""
    times = (t.get("times_with_link", "").format(booking_link=real_link) if real_link
             else t.get("times_without_link", ""))
    body = t.get(category) or ""
    return body.format(first_name=first_name or "", times=times,
                       sender_first_name=sender.get("first_name", "")).strip()


CALL_PREP = ["Ask which process costs the most manual work today, who does it, and how often.",
             "Afterwards {sender} replies with one word: qualified, not a fit, or follow up."]


def sender_name(cfg: ClientConfig) -> str:
    """The real sender's first name (private/sender.yaml), or a neutral word when it is not set yet."""
    sender, real = load_sender(cfg)
    return (sender.get("first_name") or "the sender") if real else "the sender"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "company"


def write_brief(cfg: ClientConfig, conn, contact_id: int, reply: dict) -> Path:
    c = dict(conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone())
    a = dict(conn.execute("SELECT * FROM accounts WHERE id=?", (c["account_id"],)).fetchone())
    s = conn.execute("SELECT * FROM l2_scores WHERE account_id=?", (a["id"],)).fetchone()
    d = conn.execute("SELECT * FROM drafts WHERE contact_id=?", (contact_id,)).fetchone()
    ev = conn.execute("SELECT DISTINCT signal, label, url FROM evidence WHERE account_id=?", (a["id"],)).fetchall()
    first_email = json.loads(d["steps_json"])[0]["body"] if d else ""
    who = sender_name(cfg)
    call_prep = [line.replace("{sender}", who) for line in _templates(cfg).get("call_prep", CALL_PREP)]
    lines = [
        f"# Meeting brief: {a['name']}",
        "",
        (f"Reply received {reply.get('received_at') or ''} ({reply['category']}). "
         f"Quailworks answers within 4 working hours; {who} only takes the call."),
        "",
        "## The company",
        f"- Website: {a.get('website') or a.get('domain') or 'unknown'}",
        (f"- Country: {a.get('country') or 'unknown'}; size: {a.get('employee_range') or 'unknown'} employees; "
         f"industry: {a.get('industry') or 'unknown'}"),
    ]
    if s:
        lines.append(f"- Our score: {s['tier'].replace('_', ' ').title()}, fit {s['fit']}, signals {s['signal']}")
        titles = json.loads(s["job_titles"] or "[]")
        if titles:
            lines.append(f"- Open roles seen: {', '.join(titles[:8])}")
    if ev:
        lines += ["", "## Why we wrote to them (with sources)"]
        lines += [f"- {e['label']} ({e['url']})" for e in ev]
    lines += [
        "", "## The person",
        (f"- {c.get('full_name') or (c.get('first_name') or '') + ' ' + (c.get('last_name') or '')}, "
         f"{c.get('title') or 'title unknown'} ({c.get('persona') or 'persona unknown'})"),
        f"- Email: {c.get('email')}; LinkedIn: {c.get('linkedin_url') or 'unknown'}",
        "", "## What they received (email 1)",
        f"Subject: {d['subject'] if d else ''}", "", first_email.strip(),
        "", "## Their reply", "", (reply.get("text") or "").strip(),
        "", f"## First answer to send (Smartlead inbox, in {who}'s name)", "",
        suggested_reply(cfg, reply["category"], c.get("first_name") or ""),
        "", "## For the call",
        *[f"- {line}" for line in call_prep],
    ]
    out_dir = data_dir() / "briefs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{(reply.get('received_at') or db.now_iso())[:10]}-{_slug(a['name'])}-{contact_id}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def handoff(cfg: ClientConfig, conn) -> dict:
    """Turn unhandled replies into deals and briefs. Free; sends nothing."""
    totals = {"briefs": 0, "later": 0, "closed": 0, "paths": []}
    rows = conn.execute(
        "SELECT r.* FROM replies r WHERE r.client=? AND r.handled=0 ORDER BY r.received_at, r.id",
        (cfg.slug,)).fetchall()
    latest: dict[int, dict] = {}
    for r in rows:                       # the latest reply per contact decides
        latest[r["contact_id"]] = dict(r)
    ts = db.now_iso()
    for contact_id, reply in latest.items():
        account_id = conn.execute("SELECT account_id FROM contacts WHERE id=?", (contact_id,)).fetchone()[0]
        exists = conn.execute("SELECT stage FROM deals WHERE contact_id=?", (contact_id,)).fetchone()
        if reply["category"] in NEEDS_HUMAN:
            path = write_brief(cfg, conn, contact_id, reply)
            if exists:
                conn.execute("UPDATE deals SET reply_category=?, brief_path=?, updated_at=? WHERE contact_id=?",
                             (reply["category"], str(path), ts, contact_id))
            else:
                conn.execute("INSERT INTO deals(client, contact_id, account_id, stage, reply_category, brief_path,"
                             " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                             (cfg.slug, contact_id, account_id, "interested", reply["category"], str(path), ts, ts))
            totals["briefs"] += 1
            totals["paths"].append(str(path))
        elif reply["category"] == "not_now" and not exists:
            conn.execute("INSERT INTO deals(client, contact_id, account_id, stage, reply_category, outcome_note,"
                         " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (cfg.slug, contact_id, account_id, "later", "not_now", "asked to come back later", ts, ts))
            totals["later"] += 1
        else:
            totals["closed"] += 1
        conn.execute("UPDATE replies SET handled=1 WHERE client=? AND contact_id=?", (cfg.slug, contact_id))
    conn.commit()
    return totals


def record_outcome(cfg: ClientConfig, conn, contact_id: int, stage: str, value_eur: float | None = None,
                   note: str | None = None) -> dict:
    stage = WORDS.get(stage.strip().lower(), stage.strip().lower())
    if stage not in STAGES:
        raise ValueError(f"Unknown stage '{stage}'. Use one of: {', '.join(STAGES)}")
    deal = conn.execute("SELECT * FROM deals WHERE client=? AND contact_id=?", (cfg.slug, contact_id)).fetchone()
    if not deal:
        raise ValueError(f"No deal for contact {contact_id}. Run handoff first.")
    conn.execute("UPDATE deals SET stage=?, value_eur=COALESCE(?, value_eur), outcome_note=COALESCE(?, outcome_note),"
                 " updated_at=? WHERE id=?", (stage, value_eur, note, db.now_iso(), deal["id"]))
    if stage == "won":
        _add_won_client(cfg, conn, deal["account_id"])
    conn.commit()
    return dict(conn.execute("SELECT * FROM deals WHERE id=?", (deal["id"],)).fetchone())


def _add_won_client(cfg: ClientConfig, conn, account_id: int) -> None:
    """A won company is a client now: never cold-email it again, and find more like it."""
    a = conn.execute("SELECT a.*, s.home_title, s.home_excerpt FROM accounts a LEFT JOIN l2_scores s"
                     " ON s.account_id=a.id WHERE a.id=?", (account_id,)).fetchone()
    if a["domain"]:
        db.add_suppression(conn, cfg.slug, "domain", a["domain"], "won client")
    db.add_suppression(conn, cfg.slug, "company", a["name"], "won client")
    if not conn.execute("SELECT 1 FROM best_clients WHERE client=? AND domain IS ?", (cfg.slug, a["domain"])).fetchone():
        conn.execute("INSERT INTO best_clients(client, name, domain, industry, employees, why_they_bought, home_title,"
                     " home_excerpt, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (cfg.slug, a["name"], a["domain"], a["industry"], a["employee_range"],
                      "won through outbound", a["home_title"], (a["home_excerpt"] or "")[:300], db.now_iso()))


def pipeline(cfg: ClientConfig, conn) -> dict:
    rows = conn.execute("SELECT stage, COUNT(*) n, SUM(COALESCE(value_eur,0)) v FROM deals WHERE client=?"
                        " GROUP BY stage", (cfg.slug,)).fetchall()
    by_stage = {r["stage"]: r["n"] for r in rows}
    value = {r["stage"]: r["v"] or 0 for r in rows}
    return {"by_stage": by_stage,
            "meetings_held": sum(n for s, n in by_stage.items() if s in MEETING_HELD),
            "open_pipeline_eur": sum(v for s, v in value.items() if s in OPEN),
            "won": by_stage.get("won", 0), "won_eur": value.get("won", 0)}


# ---------- HubSpot mirror ----------

@dataclass
class CrmPlan:
    creates: list[dict] = field(default_factory=list)
    updates: list[dict] = field(default_factory=list)


def plan_crm(cfg: ClientConfig, conn) -> CrmPlan:
    plan = CrmPlan()
    rows = conn.execute(
        "SELECT d.*, a.name AS company, a.domain, a.country, a.employee_range, c.email, c.first_name, c.last_name,"
        " c.title, c.data_source FROM deals d JOIN accounts a ON a.id=d.account_id JOIN contacts c ON c.id=d.contact_id"
        " WHERE d.client=? AND (d.hubspot_synced_at IS NULL OR d.updated_at > d.hubspot_synced_at) ORDER BY d.id",
        (cfg.slug,)).fetchall()
    for r in rows:
        (plan.updates if r["hubspot_deal_id"] else plan.creates).append(dict(r))
    return plan


def sync_crm(cfg: ClientConfig, conn, plan: CrmPlan, hs) -> dict:
    """Create or update HubSpot records for the planned deals. Only call after the user approved CRM writes."""
    totals = {"created": 0, "updated": 0}
    prefix = cfg.client.get("display_name", cfg.slug)
    for r in plan.creates:
        company_id = (hs.find("companies", "domain", r["domain"]) if r["domain"] else None) or hs.create(
            "companies", {"name": r["company"], "domain": r["domain"], "country": r["country"]})
        contact_id = hs.find("contacts", "email", r["email"]) or hs.create(
            "contacts", {"email": r["email"], "firstname": r["first_name"], "lastname": r["last_name"],
                         "jobtitle": r["title"]}, [(company_id, CONTACT_TO_COMPANY)])
        deal_id = hs.create("deals", {
            "dealname": f"{prefix} | {r['company']}", "pipeline": "default",
            "dealstage": HUBSPOT_STAGE[r["stage"]], "amount": r["value_eur"],
            "description": (f"Outbound for {prefix}. Reply: {r['reply_category']}. Stage: {r['stage']}. "
                            f"Contact data source: {r['data_source']} (GDPR Art. 14).")},
            [(contact_id, DEAL_TO_CONTACT), (company_id, DEAL_TO_COMPANY)])
        conn.execute("UPDATE deals SET hubspot_company_id=?, hubspot_contact_id=?, hubspot_deal_id=?,"
                     " hubspot_synced_at=? WHERE id=?", (company_id, contact_id, deal_id, db.now_iso(), r["id"]))
        totals["created"] += 1
    for r in plan.updates:
        hs.update("deals", r["hubspot_deal_id"], {"dealstage": HUBSPOT_STAGE[r["stage"]], "amount": r["value_eur"]})
        conn.execute("UPDATE deals SET hubspot_synced_at=? WHERE id=?", (db.now_iso(), r["id"]))
        totals["updated"] += 1
    conn.commit()
    return totals
