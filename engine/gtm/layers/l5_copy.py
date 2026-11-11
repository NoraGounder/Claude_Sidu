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

What is client-specific lives in templates/sequence.yaml; without these keys The Marble Jar's
behaviour applies:
  hooks.<name>.needs / .description   the fact a hook needs, and how Jev 1.14 sees it
  process.<name>.description          options for the example process (one option: no Jev question)
  named_facts                         facts quoted from evidence labels, e.g. erp: {signal, labels}
  title_role_words                    extra regex words that make a vacancy title quotable
  company_suffixes                    extra legal suffixes to drop from company names (e.g. inc, llc)
  banned_phrases                      extra phrases that block automatic approval
  cta / hooks.<hook>.cta              the ask after the opening ({cta} in a step), one for all or per hook
  quote_titles                        [{label, pattern}]: quote a clean role name found in a confirmed
                                      open title, never the raw title text
  job_title_qa / named_facts.<k>.qa   how the fact check sees a fact ("Open job on their careers page")
  company_name_cut                    separators that end a company name (LinkedIn taglines)
  angle: priority                     first supported hook in hook_priority instead of Jev's choice
The job-title fact follows the signal in ai.yaml `job_titles.signal` (default admin_job_ad).
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
from gtm.layers.l2_prefilter import evidence_key, evidence_threshold, job_signal
from gtm.layers.l4_gate import load_rules
from gtm.signals import DEFAULT_RULES, SignalRules, rules_for
from gtm.sources.jev import JevClient, JevResult, check_policy

LEGAL_SUFFIX = re.compile(r"\s*,?\s*\b(b\.?\s?v\.?|n\.?\s?v\.?|v\.?o\.?f\.?)\s*$", re.I)
ERP_LABELS = {"Exact", "AFAS", "SAP", "Microsoft Dynamics", "Twinfield", "Unit4"}

# The Marble Jar's defaults; a client's templates/sequence.yaml overrides them (see the module docstring).
DEFAULT_NAMED_FACTS = {"erp": {"signal": "erp_mention", "labels": sorted(ERP_LABELS)}}
DEFAULT_HOOKS = {
    "admin_job_ad": {"needs": "job_title", "description": "Open with the admin job vacancy they are hiring for"},
    "growth": {"needs": "open_roles", "description": "Open with how many roles they are hiring for (growth)"},
    "erp_mention": {"needs": "erp", "description": "Open with the ERP system they use"},
    "generic": {"needs": None, "description": "Open with the general problem of retyping orders and invoices"},
}
DEFAULT_PROCESS = {"invoices": "Invoice handling: accounts payable, approvals, booking (finance roles)",
                   "orders": "Order handling: order intake and entry, planning (operations roles)"}


def hook_meta(seq: dict, hook: str) -> dict:
    own = {k: v for k, v in (seq["hooks"].get(hook) or {}).items() if k in ("needs", "description")}
    return DEFAULT_HOOKS.get(hook, {"needs": None, "description": hook}) | own


def named_facts(seq: dict) -> dict:
    return seq.get("named_facts", DEFAULT_NAMED_FACTS)


def _extra(words: str | None) -> re.Pattern | None:
    return re.compile(words, re.I) if words else None


def load_sequence(cfg: ClientConfig) -> dict:
    with (Path(cfg.root) / "templates" / "sequence.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_sender(cfg: ClientConfig) -> tuple[dict, bool]:
    """(sender fields, is_real). Without private/sender.yaml, drafts are previews only."""
    real = cfg.private_dir / "sender.yaml"
    path = real if real.exists() else Path(cfg.root) / "sender.example.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh), real.exists()


def clean_company(name: str, extra_suffixes: list[str] | None = None, cut: list[str] | None = None) -> str:
    """Company name for a sentence. `cut` (sequence.yaml company_name_cut) drops LinkedIn taglines:
    "Vimachem - IIoT Pharma 4.0 AI Platform" -> "Vimachem"."""
    for sep in cut or []:
        head = name.split(sep)[0].strip()
        if sep in name and len(head) >= 2:
            name = head
    out = LEGAL_SUFFIX.sub("", name.strip())
    if extra_suffixes:
        alts = "|".join(re.escape(s).replace(r"\.", r"\.?") for s in extra_suffixes)
        out = re.sub(rf"\s*,?\s*\b({alts})\.?\s*$", "", out, flags=re.I)
    return out or name.strip()


MAX_TITLE_WORDS = 5
MAX_TITLE_CHARS = 40


# A quoted vacancy title must name a role; internships and fragments ("Fulltime", "Kantoor") are not used.
ROLE_WORD = re.compile(r"medewerk|administrat|assist|co[oö]rdinat|specialist|officer|clerk|beheerder|planner|"
                       r"controller|boekhoud|binnendienst|backoffice|back office|orderverwerk|order entry|"
                       r"crediteur|debiteur|facturat|representative|secretar|receptionist", re.I)
PERSON_NOUN = re.compile(r"(medewerker|administrator|co[oö]rdinator|beheerder|planner|controller|assistent|assistant|"
                         r"specialist|boekhouder|secretaresse|officer|clerk|representative)$", re.I)
NOT_A_JOB = re.compile(r"stage|stagiair|intern\b|internship|trainee|werkstudent|bijbaan|vakantie", re.I)


def _fix_encoding(text: str) -> str:
    if "Ã" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
    return text


def _names_role(text: str, extra: re.Pattern | None) -> bool:
    return bool(ROLE_WORD.search(text) or (extra and extra.search(text)))


def clean_title(title: str, extra: re.Pattern | None = None) -> str:
    t = re.sub(r"\(.*?\)", "", _fix_encoding(title))   # hours, locations in brackets
    parts = [p for p in re.split(r"\s+[-–|/]\s+|\s{2,}|[,?!:;/]", t) if p.strip()] or [t]
    t = next((p for p in parts if _names_role(p, extra)), parts[0])   # "Fulltime / Accounts Administrator"
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    if not any(len(w) > 1 and w.isupper() for w in t.split()):
        t = t[:1].lower() + t[1:]
        t = " ".join(w if any(c.isupper() for c in w[1:]) else w.lower() for w in t.split())
    return t


def usable_title(title: str, extra: re.Pattern | None = None) -> bool:
    """A job title we can quote in a sentence: short, names a role, not an internship, no slogan."""
    return (0 < len(title.split()) <= MAX_TITLE_WORDS and len(title) <= MAX_TITLE_CHARS
            and _names_role(title, extra) and not NOT_A_JOB.search(title)
            and (len(title.split()) > 1 or bool(PERSON_NOUN.search(title))))   # "Administratie" is a department


def clean_first_name(name: str) -> str:
    name = (name or "").strip()
    return name.title() if name.isupper() or name.islower() else name


def facts_for(conn, account: dict, seq: dict | None = None, rules: SignalRules = DEFAULT_RULES,
              title_signal: str = "admin_job_ad", confirmed_from: float | None = None) -> dict:
    """Facts with sources. Only exact titles found on the careers page are used as job titles.
    With `confirmed_from` (the client has Jev 1.14 check job-ad word matches, ai.yaml `job_evidence`),
    a role in a match that Jev confirmed as an open vacancy can be quoted too."""
    seq = seq or {}
    extra = _extra(seq.get("title_role_words"))
    facts: dict = {}
    score = conn.execute("SELECT * FROM l2_scores WHERE account_id=?", (account["id"],)).fetchone()
    titles = json.loads(score["job_titles"] or "[]") if score else []
    careers = score["careers_url"] if score else None
    ev = conn.execute("SELECT signal, label, url, quote FROM evidence WHERE account_id=?", (account["id"],)).fetchall()

    jev_titles = [e["label"].removeprefix("job title: ") for e in ev
                  if e["signal"] == title_signal and e["label"].startswith("job title: ")]
    rule_titles = [t for t in titles
                   if any(re.search(p, t, re.I) for _, p in rules.rules.get(title_signal, []))]
    quote = seq.get("quote_titles")
    if quote:
        # Quote a clean role name when a confirmed open title contains it. Careers pages often glue the
        # job description onto the title, so the title text itself is never quoted.
        for t in jev_titles + rule_titles:
            hit = next((q for q in quote if re.search(q["pattern"], t, re.I)), None) if t in titles else None
            if hit:
                facts["job_title"] = {"value": hit["label"], "raw": t, "source": careers}
                break
        if "job_title" not in facts and confirmed_from is not None:
            row = conn.execute("SELECT checks_json FROM jev_decisions WHERE account_id=?", (account["id"],)).fetchone()
            checks = json.loads(row["checks_json"] or "{}") if row else {}
            patterns = dict(rules.rules.get(title_signal, []))
            for e in ev:
                if e["signal"] != title_signal or e["label"].startswith("job title: "):
                    continue
                if checks.get(evidence_key(e["label"], e["quote"]), 0.0) < confirmed_from:
                    continue
                m = re.search(patterns.get(e["label"]) or re.escape(e["label"]), e["quote"], re.I)
                role = re.sub(r"\s+", " ", m.group(0)).lower() if m else e["label"]
                if role.endswith("s") and not e["label"].endswith("s"):
                    role = role[:-1]                     # "account executives" -> "account executive"
                hit = next((q for q in quote if re.search(q["pattern"], role, re.I)), None)
                facts["job_title"] = {"value": hit["label"] if hit else role, "raw": e["quote"], "source": e["url"]}
                break
    else:
        exact = next((t for t in jev_titles + rule_titles
                      if t in titles and usable_title(clean_title(t, extra), extra)), None)
        if exact:
            facts["job_title"] = {"value": clean_title(exact, extra), "raw": exact, "source": careers}
    if "job_title" in facts and seq.get("job_title_qa"):
        facts["job_title"]["qa"] = seq["job_title_qa"]
    if len(titles) >= 5:
        facts["open_roles"] = {"value": len(titles), "source": careers}
    for key, spec in named_facts(seq).items():
        labels = set(spec.get("labels") or [])
        hit = next((e for e in ev if e["signal"] == spec["signal"] and (not labels or e["label"] in labels)), None)
        if hit:
            facts[key] = {"value": hit["label"], "source": hit["url"], "quote": hit["quote"]}
            if spec.get("qa"):
                facts[key]["qa"] = spec["qa"]       # tells the fact check where this fact was found
    return facts


def supported_hooks(seq: dict, facts: dict) -> list[str]:
    hooks = []
    for h in seq["hook_priority"]:
        needs = hook_meta(seq, h)["needs"]
        if needs is None or needs in facts:
            hooks.append(h)
    return hooks


def fact_values(seq: dict, facts: dict) -> dict:
    """Template placeholders filled from facts; empty when a fact is missing (hooks guard their use)."""
    values = {"job_title": facts.get("job_title", {}).get("value", ""),
              "open_roles": facts.get("open_roles", {}).get("value", "")}
    for key in named_facts(seq):
        values[key] = facts.get(key, {}).get("value", "")
    return values


def _pick(options: list[str], contact_id: int, salt: str) -> str:
    digest = hashlib.sha1(f"{contact_id}:{salt}".encode()).hexdigest()
    return options[int(digest, 16) % len(options)]


def choose_request(seq: dict, account: dict, contact: dict, hooks: list[str],
                   seller: dict | None = None) -> tuple[dict, dict]:
    """Jev 1.14 questions for this contact: the example process (only when there is a choice) and the
    opening angle (only when more than one hook is supported). Empty when there is nothing to choose."""
    state = {"company": account["name"], "industry": account.get("industry"),
             "contact_job_title": contact.get("title"), "contact_persona": contact.get("persona")}
    if seller:
        state["seller_context"] = seller
    questions = {}
    if len(seq["process"]) > 1:
        questions["process"] = {
            "type": "choice",
            "instructions": seq.get("process_question", "Which example process will matter most to this person?"),
            "criteria": {k: (v or {}).get("description") or DEFAULT_PROCESS.get(k, k)
                         for k, v in seq["process"].items()}}
    # sequence.yaml angle: priority -> the first supported hook in hook_priority, no Jev choice.
    if len(hooks) > 1 and seq.get("angle") != "priority":
        questions["angle"] = {"type": "choice",
                              "instructions": "Which opening will feel most relevant to this person?",
                              "criteria": {h: hook_meta(seq, h)["description"] for h in hooks}}
    return state, questions


def render(seq: dict, lang: str, hook: str, process: str, facts: dict, contact: dict, account: dict,
           sender: dict, gdpr: str) -> tuple[str, list[dict]]:
    values = {
        "first_name": clean_first_name(contact["first_name"]),
        "company": clean_company(account["name"], seq.get("company_suffixes"), seq.get("company_name_cut")),
        **fact_values(seq, facts),
        "sender_first_name": sender.get("first_name", ""),
        "gdpr_notice": gdpr,
    }
    values["greeting"] = _pick(seq["greetings"][lang], contact["id"], "greeting")
    values["signoff"] = _pick(seq["signoffs"][lang], contact["id"], "signoff")
    values["process"] = seq["process"][process][lang]
    values["hook"] = seq["hooks"][hook][lang].format(**values)
    # Optional: the ask that follows the opening, per hook (hooks.<hook>.cta) or one for all (cta).
    cta = seq["hooks"][hook].get("cta") or seq.get("cta") or {}
    values["cta"] = cta.get(lang, "").format(**values)
    subject = seq["hooks"][hook]["subject"][lang].format(**values)
    steps = []
    for step in seq["steps"]:
        body = step[lang].format(**values).strip()
        steps.append({"day": step["day"], "body": re.sub(r"\n{3,}", "\n\n", body)})
    return subject, steps


def qa_request(facts: dict, account: dict, email: str, seller_name: str = "The Marble Jar") -> tuple[dict, dict]:
    fact_lines = [f"Company name: {account['name']}"] + [f"{v.get('qa') or k}: {v['value']}" for k, v in facts.items()]
    state = {"facts_about_the_recipient_company": fact_lines, "email": email}
    questions = {"unsupported_claim": {
        "type": "noul",
        "instructions": ("Does the email state anything about the recipient's company that is NOT supported by "
                         f"the facts list? Statements about {seller_name}'s own offer, and general statements "
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
    signal_rules, title_signal = rules_for(cfg.scoring), job_signal(cfg)
    sender, sender_real = load_sender(cfg)
    done = "" if redo else " AND c.id NOT IN (SELECT contact_id FROM drafts WHERE status != 'rejected')"
    rows = [dict(r) for r in conn.execute(
        "SELECT c.*, a.name AS company_name FROM contacts c JOIN accounts a ON a.id=c.account_id"
        " WHERE c.client=? AND (c.status='ready' OR (c.status='held' AND (c.status_reason='sender_consent_pending'"
        " OR c.status_reason LIKE 'unverified_email%')))"   # previews may be drafted before verification; push needs 'ready'
        f"{done} ORDER BY c.id", (cfg.slug,)).fetchall()]
    rows = rows[:limit] if limit else rows
    jev = jev or JevClient(cfg.ai)
    totals = {"drafted": 0, "needs_review": 0, "preview": 0, "hooks": {}}
    for contact in rows:
        account = dict(conn.execute("SELECT * FROM accounts WHERE id=?", (contact["account_id"],)).fetchone())
        # Language comes from client.yaml: one default, with optional per-country overrides.
        lang_cfg = cfg.client.get("language", {})
        lang = (lang_cfg.get("by_country") or {}).get(account.get("country") or "", lang_cfg.get("default", "en"))
        facts = facts_for(conn, account, seq, signal_rules, title_signal,
                          evidence_threshold(cfg) if cfg.ai.get("job_evidence") else None)
        hooks = supported_hooks(seq, facts)

        state, questions = choose_request(seq, account, contact, hooks, brain.jev_context(cfg, "angle"))
        answers: dict = {}
        if questions:
            choice = jev.decide(state, questions)      # JevUnavailable stops the run: no fallback
            _log_jev(conn, cfg, account["id"], choice)
            answers = choice.answers
        process = answers["process"]["choice"] if "process" in answers else next(iter(seq["process"]))
        hook = answers["angle"]["choice"] if "angle" in answers else hooks[0]
        angle_p = (answers.get("angle", {}).get("probabilities") or {}).get(hook)

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
    hook_text = seq["hooks"][hook][lang].format(
        company=clean_company(account["name"], seq.get("company_suffixes"), seq.get("company_name_cut")),
        **fact_values(seq, facts))
    qa_text = f"Subject: {subject}\n{hook_text}"
    for name, placeholder in ((clean_first_name(contact["first_name"]), "[first name]"),
                              (contact.get("last_name") or "", "[last name]"),
                              (sender.get("first_name") or "", "[sender]")):
        if name:
            qa_text = re.sub(rf"\b{re.escape(name)}\b", placeholder, qa_text)
    qa_state, qa_questions = qa_request(facts, account, qa_text, cfg.client.get("display_name", cfg.slug))
    qa = jev.decide(qa_state, qa_questions)
    _log_jev(conn, cfg, account["id"], qa)
    return float(qa.answers["unsupported_claim"]["noul"])


BANNED = ("mendix", "pebls", "fixed price", "vaste prijs", "free of charge", "kosteloos", "existing systems",
          "bestaande systemen", "working days", "werkdagen")


def auto_approve(cfg: ClientConfig, conn) -> dict:
    """Quailworks' own review (decisions.md, rule 8): approve drafts that passed every automatic check.
    A draft is approved only when it is a real draft (sender known), Jev 1.14 found no unsupported claim,
    the GDPR notice is in email 1, every step is filled in, and no banned claim appears. The rest stay
    for a person (export-drafts)."""
    rules = load_rules(cfg)
    banned = BANNED + tuple(p.lower() for p in load_sequence(cfg).get("banned_phrases", []))
    threshold = cfg.ai["thresholds"]["unsupported_claim"]
    counts = {"approved": 0, "left_for_review": 0}
    ts = db.now_iso()
    for d in conn.execute("SELECT * FROM drafts WHERE client=? AND status IN ('draft','needs_review')",
                          (cfg.slug,)).fetchall():
        steps = json.loads(d["steps_json"])
        text = " ".join(s["body"] for s in steps).lower() + " " + d["subject"].lower()
        ok = (d["status"] == "draft" and (d["qa_unsupported_p"] or 0) < threshold
              and rules["gdpr_notice"][d["language"]] in steps[0]["body"]
              and all(s["body"].strip() and "{" not in s["body"] for s in steps)
              and not any(b in text for b in banned))
        if ok:
            conn.execute("UPDATE drafts SET status='approved', review_note=?, reviewed_at=?, updated_at=? WHERE id=?",
                         ("auto-approved by Quailworks: all checks passed", ts, ts, d["id"]))
            counts["approved"] += 1
        else:
            counts["left_for_review"] += 1
    conn.commit()
    return counts


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
