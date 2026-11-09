"""Layer 5: personalised email drafts from human-written templates and crawled facts only.

No AI writes text. For every contact that passed (or is only waiting on sender consent in) the
Layer 4 gate:
 1. Collect facts with their source URLs: an exact admin job title from the careers page, the number
    of open roles, an ERP system named on the site.
 2. Python builds the list of hooks the facts support (templates/sequence.yaml `hook_priority`).
 3. TypeSafe Jev 1.14 picks the opening angle among the supported hooks and the example process
    (invoices or orders) for this person. One request; no names are sent.
 4. Python renders the 4-step sequence; greeting and sign-off vary by contact deterministically.
 5. Jev 1.14 fact-checks email 1 against the facts list; any doubt marks the draft needs_review.
Quailworks reviews every draft in Google Sheets (CSV export/import) before Layer 6 may send it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import yaml

from gtm import brain, db
from gtm.config import ClientConfig, data_dir
from gtm.layers.l4_gate import load_rules
from gtm.signals import RULES
from gtm.sources.jev import JevClient, JevResult, check_policy

LEGAL_SUFFIX = re.compile(r"\s*,?\s*\b(b\.?\s?v\.?|n\.?\s?v\.?|v\.?o\.?f\.?)\s*$", re.I)
ERP_LABELS = {"Exact", "AFAS", "SAP", "Microsoft Dynamics", "Twinfield", "Unit4"}


def load_sequence(cfg: ClientConfig) -> dict:
    with (Path(cfg.root) / "templates" / "sequence.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_sender(cfg: ClientConfig) -> tuple[dict, bool]:
    """(sender fields, is_real). Without private/sender.yaml, drafts are previews only."""
    real = cfg.private_dir / "sender.yaml"
    path = real if real.exists() else Path(cfg.root) / "sender.example.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh), real.exists()


def clean_company(name: str) -> str:
    out = LEGAL_SUFFIX.sub("", name.strip())
    return out or name.strip()


MAX_TITLE_WORDS = 5
MAX_TITLE_CHARS = 40


def clean_title(title: str) -> str:
    t = re.sub(r"\(.*?\)", "", title)                  # hours, locations in brackets
    t = re.split(r"\s+[-–|/]\s+|\s{2,}|[,?!:;]", t)[0]   # trailing " - Breda", ", Antwerpen", "? Ben jij..."
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    if not any(len(w) > 1 and w.isupper() for w in t.split()):
        t = t[:1].lower() + t[1:]
        t = " ".join(w if any(c.isupper() for c in w[1:]) else w.lower() for w in t.split())
    return t


def usable_title(title: str) -> bool:
    """A job title we can quote in a sentence: short, one role, no slogan."""
    return 0 < len(title.split()) <= MAX_TITLE_WORDS and len(title) <= MAX_TITLE_CHARS


def clean_first_name(name: str) -> str:
    name = (name or "").strip()
    return name.title() if name.isupper() or name.islower() else name


def facts_for(conn, account: dict) -> dict:
    """Facts with sources. Only exact titles found on the careers page are used as job titles."""
    facts: dict = {}
    score = conn.execute("SELECT * FROM l2_scores WHERE account_id=?", (account["id"],)).fetchone()
    titles = json.loads(score["job_titles"] or "[]") if score else []
    careers = score["careers_url"] if score else None
    ev = conn.execute("SELECT signal, label, url, quote FROM evidence WHERE account_id=?", (account["id"],)).fetchall()

    jev_titles = [e["label"].removeprefix("job title: ") for e in ev
                  if e["signal"] == "admin_job_ad" and e["label"].startswith("job title: ")]
    rule_titles = [t for t in titles
                   if any(re.search(p, t, re.I) for _, p in RULES["admin_job_ad"])]
    exact = next((t for t in jev_titles + rule_titles if t in titles and usable_title(clean_title(t))), None)
    if exact:
        facts["job_title"] = {"value": clean_title(exact), "raw": exact, "source": careers}
    if len(titles) >= 5:
        facts["open_roles"] = {"value": len(titles), "source": careers}
    erp = next((e for e in ev if e["signal"] == "erp_mention" and e["label"] in ERP_LABELS), None)
    if erp:
        facts["erp"] = {"value": erp["label"], "source": erp["url"], "quote": erp["quote"]}
    return facts


def supported_hooks(seq: dict, facts: dict) -> list[str]:
    needs = {"admin_job_ad": "job_title", "growth": "open_roles", "erp_mention": "erp", "generic": None}
    return [h for h in seq["hook_priority"] if needs[h] is None or needs[h] in facts]


def _pick(options: list[str], contact_id: int, salt: str) -> str:
    digest = hashlib.sha1(f"{contact_id}:{salt}".encode()).hexdigest()
    return options[int(digest, 16) % len(options)]


def choose_request(seq: dict, account: dict, contact: dict, hooks: list[str],
                   seller: dict | None = None) -> tuple[dict, dict]:
    descriptions = {
        "admin_job_ad": "Open with the admin job vacancy they are hiring for",
        "growth": "Open with how many roles they are hiring for (growth)",
        "erp_mention": "Open with the ERP system they use",
        "generic": "Open with the general problem of retyping orders and invoices",
    }
    state = {"company": account["name"], "industry": account.get("industry"),
             "contact_job_title": contact.get("title"), "contact_persona": contact.get("persona")}
    if seller:
        state["seller_context"] = seller
    questions = {"process": {
        "type": "choice",
        "instructions": "Which example process will matter most to this person?",
        "criteria": {"invoices": "Invoice handling: accounts payable, approvals, booking (finance roles)",
                     "orders": "Order handling: order intake and entry, planning (operations roles)"}}}
    if len(hooks) > 1:
        questions["angle"] = {"type": "choice",
                              "instructions": "Which opening will feel most relevant to this person?",
                              "criteria": {h: descriptions[h] for h in hooks}}
    return state, questions


def render(seq: dict, lang: str, hook: str, process: str, facts: dict, contact: dict, account: dict,
           sender: dict, gdpr: str) -> tuple[str, list[dict]]:
    values = {
        "first_name": clean_first_name(contact["first_name"]),
        "company": clean_company(account["name"]),
        "job_title": facts.get("job_title", {}).get("value", ""),
        "open_roles": facts.get("open_roles", {}).get("value", ""),
        "erp": facts.get("erp", {}).get("value", ""),
        "sender_first_name": sender.get("first_name", ""),
        "gdpr_notice": gdpr,
    }
    values["greeting"] = _pick(seq["greetings"][lang], contact["id"], "greeting")
    values["signoff"] = _pick(seq["signoffs"][lang], contact["id"], "signoff")
    values["process"] = seq["process"][process][lang]
    values["hook"] = seq["hooks"][hook][lang].format(**values)
    subject = seq["hooks"][hook]["subject"][lang].format(**values)
    steps = []
    for step in seq["steps"]:
        body = step[lang].format(**values).strip()
        steps.append({"day": step["day"], "body": re.sub(r"\n{3,}", "\n\n", body)})
    return subject, steps


def qa_request(facts: dict, account: dict, email: str) -> tuple[dict, dict]:
    fact_lines = [f"Company name: {account['name']}"] + [f"{k}: {v['value']}" for k, v in facts.items()]
    state = {"facts_about_the_recipient_company": fact_lines, "email": email}
    questions = {"unsupported_claim": {
        "type": "noul",
        "instructions": ("Does the email state anything about the recipient's company that is NOT supported by "
                         "the facts list? Statements about The Marble Jar's own offer, and general statements "
                         "about companies like theirs, do not count."),
        "criteria": {"true": "At least one claim about the company is not supported by the facts",
                     "false": "Every claim about the company is supported by the facts"}}}
    return state, questions


def _log_jev(conn, cfg, account_id, result: JevResult) -> None:
    conn.execute(
        "INSERT INTO jev_calls(client, account_id, requested_model, model_id, input_tokens, output_tokens,"
        " cost_usd, latency_ms, request_id, status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cfg.slug, account_id, cfg.ai["model"], result.model_id, result.input_tokens, result.output_tokens,
         result.cost_usd, result.latency_ms, result.request_id, "succeeded", None, db.now_iso()))


def draft(cfg: ClientConfig, conn, jev: JevClient | None = None, redo: bool = False, limit: int | None = None) -> dict:
    check_policy(cfg.ai)
    seq, rules = load_sequence(cfg), load_rules(cfg)
    sender, sender_real = load_sender(cfg)
    done = "" if redo else " AND c.id NOT IN (SELECT contact_id FROM drafts WHERE status != 'rejected')"
    rows = [dict(r) for r in conn.execute(
        "SELECT c.*, a.name AS company_name FROM contacts c JOIN accounts a ON a.id=c.account_id"
        " WHERE c.client=? AND (c.status='ready' OR (c.status='held' AND c.status_reason='sender_consent_pending'))"
        f"{done} ORDER BY c.id", (cfg.slug,)).fetchall()]
    rows = rows[:limit] if limit else rows
    jev = jev or JevClient(cfg.ai)
    totals = {"drafted": 0, "needs_review": 0, "preview": 0, "hooks": {}}
    for contact in rows:
        account = dict(conn.execute("SELECT * FROM accounts WHERE id=?", (contact["account_id"],)).fetchone())
        # Language comes from client.yaml: one default, with optional per-country overrides.
        lang_cfg = cfg.client.get("language", {})
        lang = (lang_cfg.get("by_country") or {}).get(account.get("country") or "", lang_cfg.get("default", "en"))
        facts = facts_for(conn, account)
        hooks = supported_hooks(seq, facts)

        state, questions = choose_request(seq, account, contact, hooks, brain.jev_context(cfg, "angle"))
        choice = jev.decide(state, questions)          # JevUnavailable stops the run: no fallback
        _log_jev(conn, cfg, account["id"], choice)
        process = choice.answers["process"]["choice"]
        hook = choice.answers["angle"]["choice"] if "angle" in choice.answers else hooks[0]
        angle_p = (choice.answers.get("angle", {}).get("probabilities") or {}).get(hook)

        threshold = cfg.ai["thresholds"]["unsupported_claim"]
        # Try Jev's pick first; if the fact check flags it, fall back along hook_priority (ending with
        # the neutral generic opening) instead of leaving the draft for a person.
        order = [hook] + [h for h in seq["hook_priority"] if h in hooks and h != hook]
        for attempt in order:
            subject, steps = render(seq, lang, attempt, process, facts, contact, account, sender,
                                    rules["gdpr_notice"][lang])
            unsupported = _fact_check(cfg, conn, jev, seq, lang, attempt, subject, facts, contact, account, sender)
            hook = attempt
            if unsupported < threshold:
                break
        status = "preview" if not sender_real else "needs_review" if unsupported >= threshold else "draft"
        ts = db.now_iso()
        conn.execute(
            "INSERT INTO drafts(client, contact_id, language, hook, process, subject, steps_json, facts_json,"
            " jev_angle_p, qa_unsupported_p, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(contact_id) DO UPDATE SET language=excluded.language, hook=excluded.hook,"
            " process=excluded.process, subject=excluded.subject, steps_json=excluded.steps_json,"
            " facts_json=excluded.facts_json, jev_angle_p=excluded.jev_angle_p,"
            " qa_unsupported_p=excluded.qa_unsupported_p, status=excluded.status, edited=0,"
            " updated_at=excluded.updated_at",
            (cfg.slug, contact["id"], lang, hook, process, subject, json.dumps(steps, ensure_ascii=False),
             json.dumps(facts, ensure_ascii=False), angle_p, unsupported, status, ts, ts))
        conn.commit()
        totals["drafted"] += 1
        totals["needs_review"] += unsupported >= threshold
        totals["preview"] += status == "preview"
        totals["hooks"][hook] = totals["hooks"].get(hook, 0) + 1
    return totals


def _fact_check(cfg, conn, jev, seq, lang, hook, subject, facts, contact, account, sender) -> float:
    """Jev 1.14 checks only what claims something about the company: the subject and the opening.
    Data minimisation: no names are sent."""
    hook_text = seq["hooks"][hook][lang].format(company=clean_company(account["name"]),
                                                job_title=facts.get("job_title", {}).get("value", ""),
                                                open_roles=facts.get("open_roles", {}).get("value", ""),
                                                erp=facts.get("erp", {}).get("value", ""))
    qa_text = f"Subject: {subject}\n{hook_text}"
    for name, placeholder in ((clean_first_name(contact["first_name"]), "[first name]"),
                              (contact.get("last_name") or "", "[last name]"),
                              (sender.get("first_name") or "", "[sender]")):
        if name:
            qa_text = re.sub(rf"\b{re.escape(name)}\b", placeholder, qa_text)
    qa_state, qa_questions = qa_request(facts, account, qa_text)
    qa = jev.decide(qa_state, qa_questions)
    _log_jev(conn, cfg, account["id"], qa)
    return float(qa.answers["unsupported_claim"]["noul"])


REVIEW_COLUMNS = ["draft_id", "tier", "company", "first_name", "contact_title", "language", "hook", "facts",
                  "jev_fact_check", "status", "subject", "email_1", "email_2", "email_3", "email_4",
                  "decision", "note"]


def export_review(cfg: ClientConfig, conn, out: str | None = None) -> tuple[str, int]:
    """CSV for Google Sheets (File > Import). Reviewers fill `decision` (approve/reject) and may
    edit subject and email text. Personal data: keep the file in data/ and delete the sheet after."""
    path = out or str(data_dir() / f"{cfg.slug}-drafts-review.csv")
    rows = conn.execute(
        "SELECT d.*, c.first_name, c.title, a.name AS company, s.tier FROM drafts d"
        " JOIN contacts c ON c.id=d.contact_id JOIN accounts a ON a.id=c.account_id"
        " JOIN l2_scores s ON s.account_id=a.id WHERE d.client=? AND d.status IN ('preview','draft','needs_review')"
        " ORDER BY CASE s.tier WHEN 'tier_1' THEN 1 WHEN 'tier_2' THEN 2 ELSE 3 END, d.id", (cfg.slug,)).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(REVIEW_COLUMNS)
        for r in rows:
            steps = json.loads(r["steps_json"])
            facts = json.loads(r["facts_json"])
            fact_text = "; ".join(f"{k}: {v['value']} ({v.get('source') or 'no url'})" for k, v in facts.items()) or "none"
            check = f"unsupported claim p={r['qa_unsupported_p']:.2f}" if r["qa_unsupported_p"] is not None else ""
            w.writerow([r["id"], r["tier"], r["company"], r["first_name"], r["title"], r["language"], r["hook"],
                        fact_text, check, r["status"], r["subject"], *[s["body"] for s in steps][:4], "", ""])
    return path, len(rows)


def import_review(cfg: ClientConfig, conn, path: str) -> dict:
    rules = load_rules(cfg)
    counts = {"approved": 0, "rejected": 0, "unchanged": 0, "errors": []}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            decision = (row.get("decision") or "").strip().lower()
            d = conn.execute("SELECT * FROM drafts WHERE id=? AND client=?", (row["draft_id"], cfg.slug)).fetchone()
            if not d or decision not in {"approve", "approved", "reject", "rejected"}:
                counts["unchanged"] += 1
                continue
            if decision.startswith("reject"):
                conn.execute("UPDATE drafts SET status='rejected', review_note=?, reviewed_at=? WHERE id=?",
                             (row.get("note"), db.now_iso(), d["id"]))
                counts["rejected"] += 1
                continue
            if d["status"] == "preview":
                counts["errors"].append(f"draft {d['id']}: preview only (no private/sender.yaml); re-draft first")
                continue
            steps = json.loads(d["steps_json"])
            edited = False
            for n, step in enumerate(steps[:4], start=1):
                new = (row.get(f"email_{n}") or "").replace("\r\n", "\n").strip()
                if new and new != step["body"]:
                    step["body"], edited = new, True
            subject = (row.get("subject") or d["subject"]).strip()
            if rules["gdpr_notice"][d["language"]] not in steps[0]["body"]:
                counts["errors"].append(f"draft {d['id']}: the GDPR notice was removed from email 1")
                continue
            conn.execute("UPDATE drafts SET status='approved', subject=?, steps_json=?, edited=?, review_note=?,"
                         " reviewed_at=?, updated_at=? WHERE id=?",
                         (subject, json.dumps(steps, ensure_ascii=False), int(edited or subject != d["subject"]),
                          row.get("note"), db.now_iso(), db.now_iso(), d["id"]))
            counts["approved"] += 1
    conn.commit()
    return counts
