"""Layer 6: Smartlead campaigns, a guarded upload, an explicit start, and reply sync.

Nothing here sends by itself:
- `push` creates (or reuses) one PAUSED-by-default campaign per region, links checked mailboxes,
  sets sequence, schedule and settings, and uploads eligible leads. Smartlead's own block and
  unsubscribe lists stay on.
- `start` is the only call that makes Smartlead send. The CLI requires --i-confirm, and Claude Code
  runs it only after the user says so in the conversation (CLAUDE.md rule 3).
- `sync` pulls replies, bounces and unsubscribes back. TypeSafe Jev 1.14 classifies replies after
  emails, phone numbers and names are masked. Bounces and unsubscribes are suppressed everywhere.

Eligible = approved draft + contact `ready` in Layer 4 + sender consent granted + real sender file,
not suppressed, and no other contact of the same account active in the last `stagger_days_same_account`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from gtm import brain, db
from gtm.config import ClientConfig
from gtm.layers.l5_copy import load_sender
from gtm.sources.jev import JevClient, JevResult, check_policy
from gtm.sources.smartlead import SmartleadClient

REPLY_CATEGORIES = {
    "interested": "Wants to talk, asks for a call or a time, or says yes to the offer",
    "question": "Asks a question about the offer, price or how it works, without saying yes or no",
    "not_now": "Not now or later: timing, budget cycle, ask again in some months",
    "not_interested": "Clearly not interested, but no request to stop emailing",
    "referral": "Points to another person who handles this",
    "wrong_person": "Says they are not the right person and names no one",
    "out_of_office": "Automatic out-of-office or holiday reply",
    "unsubscribe": "Asks to stop emailing, unsubscribe or remove their address",
}
NEEDS_HUMAN = {"interested", "question", "referral"}
SUPPRESS = {"unsubscribe"}


def load_sending(cfg: ClientConfig) -> dict:
    with (Path(cfg.root) / "sending.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def region_for(sending: dict, country: str | None) -> str | None:
    for name, r in sending["regions"].items():
        if (country or "").upper() in r["countries"]:
            return name
    return None


def sequence_payload(steps_days: list[int]) -> list[dict]:
    """Template steps: everything personal comes in as custom fields. Smartlead delays are
    relative to the previous step; follow-ups have an empty subject so they thread under email 1."""
    out, prev = [], 0
    for n, day in enumerate(steps_days, start=1):
        out.append({"seq_number": n, "seq_delay_details": {"delay_in_days": day - prev},
                    "subject": "{{tmj_subject}}" if n == 1 else "",
                    "email_body": "{{tmj_email_%d}}" % n})
        prev = day
    return out


@dataclass
class PushPlan:
    eligible: dict[str, list[dict]] = field(default_factory=dict)     # region -> leads
    held: dict[str, int] = field(default_factory=dict)                # reason -> count


def plan_push(cfg: ClientConfig, conn, now: datetime | None = None) -> PushPlan:
    now = now or datetime.now(timezone.utc)
    sending = load_sending(cfg)
    plan = PushPlan()

    def hold(reason):
        plan.held[reason] = plan.held.get(reason, 0) + 1

    consent = str(cfg.client.get("sender", {}).get("consent_to_send_in_name")).lower() == "granted"
    sender, sender_real = load_sender(cfg)
    from gtm.layers.l1_discover import sync_exclusions
    sync_exclusions(conn, cfg)          # last check before upload: the do-not-contact list is current
    suppressed = {k: db.suppressed_values(conn, cfg.slug, k) for k in ("email", "domain", "company")}
    rows = [dict(r) for r in conn.execute(
        "SELECT d.id AS draft_id, d.subject, d.steps_json, c.*, a.name AS company, a.domain AS account_domain,"
        " a.country AS account_country, a.status AS account_tier FROM drafts d JOIN contacts c ON c.id=d.contact_id"
        " JOIN accounts a ON a.id=c.account_id WHERE d.client=? AND d.status='approved'"
        " AND c.id NOT IN (SELECT contact_id FROM outbound) ORDER BY c.rank, c.id", (cfg.slug,)).fetchall()]
    window = (now - timedelta(days=sending["stagger_days_same_account"])).isoformat()
    active_accounts = {r[0] for r in conn.execute(
        "SELECT account_id FROM outbound WHERE client=? AND (pushed_at >= ? OR status='replied')",
        (cfg.slug, window))}
    for r in rows:
        if not consent:
            hold("sender_consent_not_granted"); continue
        if not sender_real or not sender.get("first_name") or "<" in str(sender.get("first_name")):
            hold("sender_details_missing"); continue
        if r["status"] != "ready":
            hold(f"contact_not_ready:{r['status']}"); continue
        tiers = sending.get("send_tiers")
        if tiers and r["account_tier"] not in tiers:
            hold(f"tier_not_in_send_plan:{r['account_tier']}"); continue
        email = (r["email"] or "").lower()
        if email in suppressed["email"] or email.split("@")[-1] in suppressed["domain"] \
                or (r["account_domain"] or "") in suppressed["domain"] or r["company"].lower() in suppressed["company"]:
            hold("suppressed"); continue
        if r["account_id"] in active_accounts:
            hold("another_contact_at_this_company_is_active"); continue
        region = region_for(sending, r["account_country"])
        if not region:
            hold(f"no_region_for_country:{r['account_country']}"); continue
        steps = json.loads(r["steps_json"])
        lead = {"email": r["email"], "first_name": r["first_name"], "last_name": r["last_name"],
                "company_name": r["company"],
                "custom_fields": {"tmj_subject": r["subject"],
                                  **{f"tmj_email_{n}": s["body"] for n, s in enumerate(steps, start=1)}},
                "_contact_id": r["id"], "_account_id": r["account_id"], "_draft_id": r["draft_id"],
                "_days": [s["day"] for s in steps]}
        plan.eligible.setdefault(region, []).append(lead)
        active_accounts.add(r["account_id"])     # one contact per company per upload
    return plan


def check_mailboxes(cfg: ClientConfig, sending: dict, accounts: list[dict]) -> tuple[list[int], list[str]]:
    cap = cfg.limits.sending.get("max_per_mailbox_per_day", 18)
    # One Smartlead account serves several clients: a campaign may only use this client's own
    # sending domains (sending.yaml mailbox_domains). No list means no mailbox, never all of them.
    domains = {d.lower() for d in sending.get("mailbox_domains") or []}
    ok, problems = [], []
    for a in accounts:
        name = a.get("from_email") or a.get("email") or a.get("id")
        if str(name).rsplit("@", 1)[-1].lower() not in domains:
            continue                                   # another client's mailbox: not ours to use
        per_day = a.get("message_per_day") or a.get("max_email_per_day")
        warmup = a.get("warmup_details") or {}
        warm = a.get("warmup_enabled", warmup.get("status") == "ACTIVE")
        if a.get("is_smtp_success") is False or a.get("is_imap_success") is False:
            problems.append(f"{name}: SMTP or IMAP connection failed")
        elif warmup.get("blocked_reason"):
            problems.append(f"{name}: warm-up blocked ({warmup['blocked_reason']})")
        elif per_day and int(per_day) > cap:
            problems.append(f"{name}: sends up to {per_day}/day, cap is {cap}")
        elif sending.get("require_warmup", True) and not warm:
            problems.append(f"{name}: warm-up is off")
        else:
            ok.append(int(a["id"]))
    return ok, problems


def shared_domains(cfg: ClientConfig) -> list[str]:
    """This client's sending domains that another client also lists (clients/*/sending.yaml). One
    Smartlead account serves several clients, so a domain must belong to exactly one of them."""
    own = {d.lower() for d in load_sending(cfg).get("mailbox_domains") or []}
    clash = set()
    for f in Path(cfg.root).parent.glob("*/sending.yaml"):
        if f.parent.name != Path(cfg.root).name:
            other = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            clash |= own & {d.lower() for d in other.get("mailbox_domains") or []}
    return sorted(clash)


def push(cfg: ClientConfig, conn, sl: SmartleadClient | None = None, plan: PushPlan | None = None,
         now: datetime | None = None) -> dict:
    sending = load_sending(cfg)
    if clash := shared_domains(cfg):
        raise RuntimeError(f"Sending domains listed for another client too: {', '.join(clash)}. "
                           "Each domain belongs to one client (sending.yaml mailbox_domains).")
    plan = plan or plan_push(cfg, conn, now)
    if not plan.eligible:
        return {"pushed": 0, "held": plan.held, "campaigns": {}}
    sl = sl or SmartleadClient()
    mailbox_ids, problems = check_mailboxes(cfg, sending, sl.email_accounts())
    if not mailbox_ids:
        raise RuntimeError("No usable mailboxes: " + ("; ".join(problems) or "none on this client's mailbox_domains "
                                                       "(sending.yaml) in Smartlead"))
    ts = db.now_iso()
    totals = {"pushed": 0, "held": plan.held, "campaigns": {}, "mailbox_problems": problems}
    daily = cfg.limits.sending.get("max_emails_per_day", 120)
    for region, leads in plan.eligible.items():
        row = conn.execute("SELECT * FROM campaigns WHERE client=? AND region=?", (cfg.slug, region)).fetchone()
        if row:
            campaign_db_id, campaign_id = row["id"], row["smartlead_id"]
        else:
            r = sending["regions"][region]
            name = f"{sending['campaign_prefix']} | {region.upper()} | {ts[:7]}"
            campaign_id = sl.create_campaign(name)
            sl.save_sequences(campaign_id, sequence_payload(leads[0]["_days"]))
            s = sending["settings"]
            # Format from Smartlead's current docs (guides/campaign-setup). Verify in the Smartlead UI
            # after the first push, while the campaign is still paused.
            sl.update_settings(campaign_id, {
                "track_settings": {"track_open": bool(s["track_open"]), "track_click": bool(s["track_click"])},
                "stop_lead_settings": {"stop_on_reply": s["stop_on_reply"],
                                       "stop_on_auto_reply": s["stop_on_auto_reply"], "stop_on_click": False},
                "send_as_plain_text": s["send_as_plain_text"]})
            # Each new lead gets up to 4 emails; share the daily cap across regions.
            per_region = max(1, daily // 4 // max(1, len(sending["regions"])))
            sl.set_schedule(campaign_id, {"timezone": r["timezone"], **{k: v for k, v in sending["schedule"].items()},
                                          "max_new_leads_per_day": per_region})
            sl.link_email_accounts(campaign_id, mailbox_ids)
            cur = conn.execute("INSERT INTO campaigns(client, region, smartlead_id, name, timezone, status, created_at)"
                               " VALUES (?,?,?,?,?,?,?)", (cfg.slug, region, campaign_id, name, r["timezone"],
                                                           "DRAFTED", ts))
            campaign_db_id = cur.lastrowid
        for start in range(0, len(leads), 400):
            batch = leads[start:start + 400]
            sl.add_leads(campaign_id, [{k: v for k, v in lead.items() if not k.startswith("_")} for lead in batch])
            for lead in batch:
                conn.execute("INSERT INTO outbound(contact_id, client, account_id, draft_id, campaign_id, status,"
                             " pushed_at) VALUES (?,?,?,?,?,?,?)",
                             (lead["_contact_id"], cfg.slug, lead["_account_id"], lead["_draft_id"],
                              campaign_db_id, "pushed", ts))
            conn.commit()
        totals["pushed"] += len(leads)
        totals["campaigns"][region] = campaign_id
    return totals


def start(cfg: ClientConfig, conn, region: str, sl: SmartleadClient | None = None) -> str:
    row = conn.execute("SELECT * FROM campaigns WHERE client=? AND region=?", (cfg.slug, region)).fetchone()
    if not row:
        raise RuntimeError(f"No campaign for region '{region}'. Run push first.")
    (sl or SmartleadClient()).set_status(row["smartlead_id"], "ACTIVE")
    conn.execute("UPDATE campaigns SET status='ACTIVE' WHERE id=?", (row["id"],))
    conn.commit()
    return row["name"]


def mask(text: str, names: list[str]) -> str:
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text)
    text = re.sub(r"\+?\d[\d\s().-]{7,}\d", "[phone]", text)
    for n in names:
        if n:
            text = re.sub(rf"\b{re.escape(n)}\b", "[name]", text, flags=re.I)
    return text


def latest_reply(history: list[dict]) -> tuple[str | None, str | None]:
    replies = [h for h in history if str(h.get("type", h.get("message_type", ""))).upper() in
               {"REPLY", "REPLIED", "EMAIL_REPLY", "RECEIVED"}]
    if not replies:
        return None, None
    last = replies[-1]
    body = last.get("email_body") or last.get("body") or last.get("text") or ""
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.split(r"\n(?:On .+wrote:|Op .+schreef.+:|-----Original Message-----|From: )", body)[0]
    return re.sub(r"\s+", " ", body).strip()[:3000], last.get("time") or last.get("sent_time") or last.get("timestamp")


def sync(cfg: ClientConfig, conn, sl: SmartleadClient | None = None, jev: JevClient | None = None) -> dict:
    check_policy(cfg.ai)
    sl = sl or SmartleadClient()
    jev = jev or JevClient(cfg.ai)
    sender, _ = load_sender(cfg)
    totals = {"replies": 0, "needs_human": 0, "bounced": 0, "unsubscribed": 0, "categories": {}}
    for camp in conn.execute("SELECT * FROM campaigns WHERE client=?", (cfg.slug,)).fetchall():
        by_email = {r["email"].lower(): dict(r) for r in conn.execute(
            "SELECT o.*, c.email, c.first_name, c.last_name FROM outbound o JOIN contacts c ON c.id=o.contact_id"
            " WHERE o.campaign_id=?", (camp["id"],))}
        for status_filter, label in (("is_bounced", "bounced"), ("is_unsubscribed", "unsubscribed")):
            for lead in sl.leads(camp["smartlead_id"], emailStatus=status_filter):
                o = by_email.get(str(lead.get("email") or (lead.get("lead") or {}).get("email", "")).lower())
                if o and o["status"] != label:
                    conn.execute("UPDATE outbound SET status=?, last_sync_at=? WHERE contact_id=?",
                                 (label, db.now_iso(), o["contact_id"]))
                    db.add_suppression(conn, cfg.slug, "email", o["email"], f"smartlead:{label}")
                    totals[label] += 1
        for lead in sl.leads(camp["smartlead_id"], emailStatus="is_replied"):
            lead_obj = lead.get("lead") or lead
            o = by_email.get(str(lead_obj.get("email", "")).lower())
            if not o:
                continue
            lead_id = lead_obj.get("id") or lead.get("lead_id")
            text, when = latest_reply(sl.message_history(camp["smartlead_id"], lead_id))
            if not text or conn.execute("SELECT 1 FROM replies WHERE client=? AND contact_id=? AND received_at IS ?",
                                        (cfg.slug, o["contact_id"], when)).fetchone():
                continue
            masked = mask(text, [o["first_name"], o["last_name"], sender.get("first_name"), sender.get("full_name")])
            result: JevResult = jev.decide(
                {"reply_to_a_sales_email": masked, "seller_context": brain.jev_context(cfg, "reply")},
                {"category": {"type": "choice", "instructions": "What kind of reply is this?",
                              "criteria": REPLY_CATEGORIES}})
            conn.execute(
                "INSERT INTO jev_calls(client, account_id, requested_model, model_id, input_tokens, output_tokens,"
                " cost_usd, latency_ms, request_id, status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cfg.slug, o["account_id"], cfg.ai["model"], result.model_id, result.input_tokens,
                 result.output_tokens, result.cost_usd, result.latency_ms, result.request_id, "succeeded", None,
                 db.now_iso()))
            category = result.answers["category"]["choice"]
            p = (result.answers["category"].get("probabilities") or {}).get(category)
            conn.execute("INSERT OR IGNORE INTO replies(client, contact_id, received_at, text, category, category_p,"
                         " model_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (cfg.slug, o["contact_id"], when, text, category, p, result.model_id, db.now_iso()))
            conn.execute("UPDATE outbound SET status='replied', smartlead_lead_id=?, last_sync_at=? WHERE contact_id=?",
                         (lead_id, db.now_iso(), o["contact_id"]))
            if category in SUPPRESS:
                db.add_suppression(conn, cfg.slug, "email", o["email"], "replied: unsubscribe")
                sl.block([o["email"]])
                totals["unsubscribed"] += 1
            totals["replies"] += 1
            totals["needs_human"] += category in NEEDS_HUMAN
            totals["categories"][category] = totals["categories"].get(category, 0) + 1
        conn.commit()
    return totals
