"""ETA outreach through the shared Smartlead account: Sidarth's emails to the owners he said yes to.

    plan    every "yes" with a deliverable work email, its final text (draft + Sidarth's details from
            clients/eta/private/sender.yaml + the domain note), and why any company is held back
    push    --live: one paused campaign "ETA | US | <month>", linked only to clients/eta/sending.yaml
            mailbox_domains that are warm, with the exact text approved in the conversation as custom fields
    start   --i-confirm: the only call that makes Smartlead send (CLAUDE.md rule 3)

Two emails at most (the first and one follow-up); any reply stops the sequence. The final text of each email is
written to data/eta/outreach/final/ so what Sidarth approves is what is uploaded.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

from gtm import db
from gtm.config import data_dir
from gtm.eta import outreach

SENDER_KEYS = ("full_name", "background", "funding", "phone", "postal_address")
ACCEPT = outreach.ACCEPT

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_outbound (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    email           TEXT NOT NULL,
    campaign_id     INTEGER NOT NULL,
    status          TEXT NOT NULL,
    pushed_at       TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
CREATE TABLE IF NOT EXISTS eta_campaigns (
    client          TEXT NOT NULL,
    smartlead_id    INTEGER NOT NULL,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (client, smartlead_id)
);
"""


def ensure_schema(conn) -> None:
    outreach.ensure_schema(conn)
    conn.executescript(SCHEMA)


def load_sending(root: Path) -> dict:
    return yaml.safe_load((Path(root) / "sending.yaml").read_text(encoding="utf-8"))


def load_sender(root: Path) -> tuple[dict, list[str]]:
    """Sidarth's own details (gitignored). Returns the details and the keys still missing."""
    path = Path(root) / "private" / "sender.yaml"
    sender = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    missing = [k for k in SENDER_KEYS if not str(sender.get(k) or "").strip() or "<" in str(sender.get(k))]
    return sender, missing


def fill(text: str, sender: dict, note: str | None = None) -> str:
    """Replace the draft's {{...}} placeholders. Anything left in braces means the text is not ready."""
    funding = sender.get("funding", "").strip()
    subs = [
        (r"\{\{YOUR FULL NAME\}\}", sender.get("full_name", "")),
        (r"\{\{ONE SENTENCE ABOUT YOUR BACKGROUND[^}]*\}\}", sender.get("background", "").strip()),
        (r"\{\{HOW THE PURCHASE WOULD BE FUNDED[^}]*\}\}", funding + (f"\n\n{note.strip()}" if note else "")),
        (r" \| \{\{EMAIL\}\}", f" | {sender['email']}" if sender.get("email") else ""),
        (r"\{\{PHONE\}\}", sender.get("phone", "")),
        (r"\{\{POSTAL ADDRESS[^}]*\}\}", sender.get("postal_address", "")),
    ]
    for pattern, value in subs:
        text = re.sub(pattern, lambda _m, v=value: v, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def follow_up(company: str, first_name: str | None, sender: dict) -> str:
    greet = f"Dear {first_name}," if first_name else "Dear owner,"
    contact = " | ".join(x for x in (sender.get("phone"), sender.get("email")) if x)
    return (f"{greet}\n\nA short follow-up to my note last week about {company}. If a conversation about the "
            "company's long-term future would ever be useful, I would be glad to listen, on your timing. If not, "
            "I will not write again.\n\n"
            f"With respect,\n{sender.get('full_name', '')}\n{contact}\n{sender.get('postal_address', '')}\n"
            'If you would rather not hear from me again, reply "no".')


def plan(conn, cfg) -> dict:
    """What would be uploaded, with the final text, and what is held back and why. Calls nothing."""
    ensure_schema(conn)
    root = Path(cfg.root)
    sending = load_sending(root)
    sender, missing = load_sender(root)
    suppressed = {k: db.suppressed_values(conn, cfg.slug, k) for k in ("email", "domain", "company")}
    out = {"ready": [], "held": [], "missing_sender": missing}
    final_dir = data_dir() / "eta" / "outreach" / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    today = date.fromisoformat(db.now_iso()[:10])
    for number in outreach.decided(conn, cfg.slug, "yes"):
        company = dict(conn.execute("SELECT * FROM eta_companies WHERE client=? AND company_number=?",
                                    (cfg.slug, number)).fetchone())
        c = conn.execute("SELECT * FROM eta_contacts WHERE client=? AND company_number=?",
                         (cfg.slug, number)).fetchone()
        name = outreach.short_name(company["name"])
        if conn.execute("SELECT 1 FROM eta_outbound WHERE client=? AND company_number=?", (cfg.slug, number)).fetchone():
            out["held"].append((name, "already uploaded")); continue
        if not c or not c["email"]:
            out["held"].append((name, "no work email: send the letter by post")); continue
        if (c["email_status"] or "").upper() not in ACCEPT:
            out["held"].append((name, f"email status {c['email_status']}")); continue
        email = c["email"].lower()
        if email in suppressed["email"] or email.split("@")[-1] in suppressed["domain"] \
                or company["name"].lower() in suppressed["company"]:
            out["held"].append((name, "suppressed")); continue
        metrics = json.loads(conn.execute(
            "SELECT metrics FROM eta_screen WHERE client=? AND company_number=? AND sieve=1",
            (cfg.slug, number)).fetchone()["metrics"])
        site = conn.execute("SELECT website FROM eta_websites WHERE client=? AND company_number=?",
                            (cfg.slug, number)).fetchone()
        draft, _letter = outreach.draft(company, dict(c), metrics, site["website"] if site else None,
                                        today)
        subject_line, body = draft.split("\n", 1)
        subject = subject_line.removeprefix("Subject:").strip()
        body = fill(body, sender, sending.get("domain_note"))
        first = (c["person"] or "").split()[0].title() if c["person"] else None
        second = follow_up(name, first, sender)
        lead = {"number": number, "company": name, "email": c["email"], "person": c["person"],
                "subject": subject, "steps": [body, second]}
        slug = re.sub(r"[^a-z0-9]+", "-", company["name"].lower()).strip("-")[:50]
        (final_dir / f"{slug}.txt").write_text(
            f"To: {c['person']} <{c['email']}>\nSubject: {subject}\n\n{body}\n\n"
            f"--- follow-up, day {sending.get('follow_up_day', 7)}, only if there is no reply ---\n\n{second}\n",
            encoding="utf-8")
        if missing or any("{{" in s for s in lead["steps"]):
            out["held"].append((name, "your details are not filled in yet")); continue
        out["ready"].append(lead)
    out["final_dir"] = str(final_dir)
    return out


def push(conn, cfg, sl=None) -> dict:
    """Upload the ready leads to one paused ETA campaign. Never starts it."""
    from gtm.layers.l6_send import check_mailboxes, settings_payload, shared_domains
    from gtm.sources.smartlead import SmartleadClient

    if clash := shared_domains(cfg):
        raise RuntimeError(f"Sending domains listed for another client too: {', '.join(clash)}.")
    p = plan(conn, cfg)
    if not p["ready"]:
        return {"pushed": 0, "held": p["held"]}
    sending = load_sending(Path(cfg.root))
    sl = sl or SmartleadClient()
    mailbox_ids, problems = check_mailboxes(cfg, sending, sl.email_accounts())
    if not mailbox_ids:
        raise RuntimeError("No usable mailboxes: " + ("; ".join(problems) or "none on clients/eta/sending.yaml"
                                                       " mailbox_domains in Smartlead"))
    row = conn.execute("SELECT * FROM eta_campaigns WHERE client=? ORDER BY created_at DESC", (cfg.slug,)).fetchone()
    if row:
        campaign_id = row["smartlead_id"]
    else:
        ts = db.now_iso()
        name = f"{sending['campaign_prefix']} | US | {ts[:7]}"
        campaign_id = sl.create_campaign(name)
        conn.execute("INSERT INTO eta_campaigns(client, smartlead_id, name, status, created_at) VALUES (?,?,?,?,?)",
                     (cfg.slug, campaign_id, name, "SETUP", ts))
        conn.commit()
        day = int(sending.get("follow_up_day", 7))
        sl.save_sequences(campaign_id, [
            {"seq_number": 1, "seq_delay_details": {"delay_in_days": 0}, "subject": "{{eta_subject}}",
             "email_body": "{{eta_email_1}}"},
            {"seq_number": 2, "seq_delay_details": {"delay_in_days": day}, "subject": "",
             "email_body": "{{eta_email_2}}"}])
        sl.update_settings(campaign_id, settings_payload(sending["settings"]))
        sl.set_schedule(campaign_id, {"timezone": sending["region"]["timezone"], **sending["schedule"]})
        conn.execute("UPDATE eta_campaigns SET status='DRAFTED' WHERE client=? AND smartlead_id=?", (cfg.slug, campaign_id))
        conn.commit()
    sl.link_email_accounts(campaign_id, mailbox_ids)
    leads = [{"email": l["email"], "first_name": (l["person"] or "").split()[0].title() if l["person"] else "",
              "last_name": " ".join((l["person"] or "").split()[1:]).title(), "company_name": l["company"],
              "custom_fields": {"eta_subject": l["subject"], "eta_email_1": l["steps"][0],
                                "eta_email_2": l["steps"][1]}} for l in p["ready"]]
    sl.add_leads(campaign_id, leads)
    ts = db.now_iso()
    for l in p["ready"]:
        conn.execute("INSERT INTO eta_outbound(client, company_number, email, campaign_id, status, pushed_at)"
                     " VALUES (?,?,?,?,?,?)", (cfg.slug, l["number"], l["email"], campaign_id, "pushed", ts))
    conn.commit()
    return {"pushed": len(leads), "held": p["held"], "campaign_id": campaign_id, "mailboxes": len(mailbox_ids),
            "mailbox_problems": problems}


def start(conn, cfg, sl=None) -> str:
    from gtm.sources.smartlead import SmartleadClient

    row = conn.execute("SELECT * FROM eta_campaigns WHERE client=? ORDER BY created_at DESC", (cfg.slug,)).fetchone()
    if not row:
        raise RuntimeError("No ETA campaign yet. Run eta-send --live first.")
    (sl or SmartleadClient()).set_status(row["smartlead_id"], "ACTIVE")
    conn.execute("UPDATE eta_campaigns SET status='ACTIVE' WHERE client=? AND smartlead_id=?",
                 (cfg.slug, row["smartlead_id"]))
    conn.commit()
    return row["name"]
