"""Sidarth's decisions on deal packs, and outreach preparation for the companies he says yes to.

    decide   yes | no | more per company (eta_decisions), with an optional note
    prepare  for each "yes": the leader's work email (FullEnrich, paid, budget-guarded), the company's mailing
             address and phone from its Form 5500 filing (free), and a draft email and letter in
             data/eta/outreach/ for Sidarth to edit and approve

Nothing here sends anything. Sending needs Sidarth's approval of the exact text and a sending channel of his own
(the Quailworks and Marble Jar mailboxes belong to those clients). Contacts and drafts stay in data/ (gitignored).
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from gtm import budget, db
from gtm.config import data_dir
from gtm.eta import dol, store

VENDOR = "fullenrich"
EMAIL_KEY = "fullenrich:work_email"
ACCEPT = {"DELIVERABLE", "HIGH_PROBABILITY"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_decisions (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('yes', 'no', 'more')),
    note            TEXT,
    decided_at      TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
CREATE TABLE IF NOT EXISTS eta_contacts (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    person          TEXT,
    title           TEXT,
    email           TEXT,
    email_status    TEXT,
    address         TEXT,
    phone           TEXT,
    sources         TEXT NOT NULL,
    prepared_at     TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def decide(conn, client: str, number: str, decision: str, note: str | None = None) -> None:
    ensure_schema(conn)
    if not conn.execute("SELECT 1 FROM eta_companies WHERE client=? AND company_number=?", (client, number)).fetchone():
        raise ValueError(f"Unknown company {number}")
    conn.execute("INSERT OR REPLACE INTO eta_decisions(client, company_number, decision, note, decided_at)"
                 " VALUES (?,?,?,?,?)", (client, number, decision, note, db.now_iso()))
    conn.commit()


def decided(conn, client: str, decision: str = "yes") -> list[str]:
    ensure_schema(conn)
    return [r["company_number"] for r in conn.execute(
        "SELECT company_number FROM eta_decisions WHERE client=? AND decision=? ORDER BY decided_at", (client, decision))]


# ---------- contact details ----------

def leader(conn, client: str, number: str) -> dict | None:
    """The top-ranked leader the owner lookup found (eta_owners from FullEnrich), else the plan-filing signer."""
    from gtm.eta.owners_us import title_rank

    people = [dict(r) for r in conn.execute("SELECT name, role, source FROM eta_owners WHERE client=? AND"
                                            " company_number=?", (client, number))]
    found = sorted((p for p in people if (p["source"] or "").startswith("fullenrich")), key=lambda p: title_rank(p["role"]))
    if found and title_rank(found[0]["role"]) <= 2:
        return found[0] | {"basis": "owner lookup"}
    signer = next((p for p in people if (p["role"] or "").startswith("signed the")), None)
    return signer | {"basis": "plan-filing signer"} if signer else None


def filing_address(ein: str, years: list[int]) -> tuple[str | None, str | None]:
    """Mailing address and phone from the employer's latest Form 5500 (free, local file)."""
    csv.field_size_limit(10**8)
    for year in sorted(years, reverse=True):
        for form, (a1, a2, city, st, zp, ph, e) in (
                ("sf", ("SF_SPONS_US_ADDRESS1", "SF_SPONS_US_ADDRESS2", "SF_SPONS_US_CITY", "SF_SPONS_US_STATE",
                        "SF_SPONS_US_ZIP", "SF_SPONS_PHONE_NUM", "SF_SPONS_EIN")),
                ("large", ("SPONS_DFE_MAIL_US_ADDRESS1", "SPONS_DFE_MAIL_US_ADDRESS2", "SPONS_DFE_MAIL_US_CITY",
                           "SPONS_DFE_MAIL_US_STATE", "SPONS_DFE_MAIL_US_ZIP", "SPONS_DFE_PHONE_NUM",
                           "SPONS_DFE_EIN"))):
            path = dol.csv_path(year, form)
            if not path.exists():
                continue
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    if (row.get(e) or "").strip() == ein:
                        addr = ", ".join(x.strip() for x in (row.get(a1), row.get(a2), row.get(city)) if x and x.strip())
                        addr = f"{addr}, {row.get(st, '').strip()} {(row.get(zp) or '')[:5]}".strip(", ")
                        phone = re.sub(r"\D", "", row.get(ph) or "")
                        phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}" if len(phone) == 10 else None
                        return addr, phone
    return None, None


def find_email(conn, cfg, fe, number: str, person: dict, domain: str) -> tuple[str | None, str | None, float]:
    parts = (person["name"] or "").split()
    if len(parts) < 2:
        return None, None, 0.0
    budget.check(conn, cfg, VENDOR, budget.estimate(cfg, EMAIL_KEY, 1))
    run_id = db.start_run(conn, cfg.slug, "eta_outreach", VENDOR, "work email x1",
                          budget.estimate(cfg, EMAIL_KEY, 1), {"company": number})
    try:
        eid = fe.start_enrichment(f"eta outreach {db.now_iso()[:16]}", [{
            "first_name": parts[0].title(), "last_name": parts[-1].title(), "domain": domain,
            "enrich_fields": ["contact.work_emails"], "custom": {"company": number}}])
        result = fe.wait_enrichment(eid)
    except Exception as exc:
        db.finish_run(conn, run_id, "failed", 0, None, str(exc)[:300])
        raise
    credits = float((result.get("cost") or {}).get("credits") or 0)
    item = (result.get("data") or [{}])[0]
    best = (item.get("contact_info") or {}).get("most_probable_work_email") or {}
    email, status = best.get("email"), (best.get("status") or "").upper() or None
    db.finish_run(conn, run_id, "succeeded", 1, round(credits * budget.estimate(cfg, "fullenrich:credit", 1), 4), eid)
    return email, status, credits


# ---------- drafts ----------

SUFFIX = re.compile(r"[,\s]+(inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|pc|p\.c)\.?$", re.I)


def short_name(name: str) -> str:
    """'MEYER & DEPEW COMPANY, INC.' -> 'Meyer & Depew': how a person would write it."""
    text = (name or "").strip()
    while (cut := SUFFIX.sub("", text)) != text:
        text = cut
    return text.title()


def draft(company: dict, contact: dict, metrics: dict, website: str | None, today: date) -> tuple[str, str]:
    first = (contact.get("person") or "").split()[0].title() if contact.get("person") else None
    since = metrics.get("plan_since")
    years = f"more than {today.year - since} years in business" if since else "many years in business"
    city = (company["locality"] or "").split(",")[0].title()
    name = short_name(company["name"])
    greet = f"Dear {first}," if first else "Dear owner,"
    before, now = metrics.get("active_before"), metrics.get("headcount")
    grown = ", and a team that has grown" if before and now and now > before else ""
    email = f"""Subject: {name}: a question about the long term

{greet}

My name is {{{{YOUR FULL NAME}}}}. I am looking to buy one company to own and run myself for the long term. I am an individual buyer, not a private equity fund and not a broker.

{name} stood out to me: {years}{' in ' + city if city else ''}{grown}. That kind of steady, well-run business is exactly what I hope to spend the next part of my career building on.

If you have ever thought about what happens to the company when you step back, I would value 20 minutes to introduce myself and listen. If the timing is wrong, I understand, and I will not follow up more than once.

{{{{ONE SENTENCE ABOUT YOUR BACKGROUND, e.g. what you did before and why this kind of business}}}} {{{{HOW THE PURCHASE WOULD BE FUNDED, e.g. your own capital and long-term investors, no bank debt}}}}

With respect,
{{{{YOUR FULL NAME}}}}
{{{{PHONE}}}} | {{{{EMAIL}}}}
{{{{POSTAL ADDRESS (US law requires one in commercial email)}}}}
If you would rather not hear from me again, reply "no" and I will not write again.
"""
    letter = email.split("\n", 2)[2].replace("If you would rather not hear from me again, reply \"no\" and I will not "
                                             "write again.\n", "")
    return email, letter


def prepare(conn, cfg, eta: dict, fe=None, today: date | None = None, find_emails: bool = True) -> dict:
    ensure_schema(conn)
    today = today or date.today()
    out_dir = data_dir() / "eta" / "outreach"
    out_dir.mkdir(parents=True, exist_ok=True)
    years = [int(y) for y in (eta.get("us") or {}).get("form5500_years") or []]
    out = {"companies": 0, "emails": 0, "addresses": 0, "credits": 0.0, "files": []}
    for number in decided(conn, cfg.slug, "yes"):
        company = dict(conn.execute("SELECT * FROM eta_companies WHERE client=? AND company_number=?",
                                    (cfg.slug, number)).fetchone())
        metrics = json.loads(conn.execute("SELECT metrics FROM eta_screen WHERE client=? AND company_number=?"
                                          " AND sieve=1", (cfg.slug, number)).fetchone()["metrics"])
        site = conn.execute("SELECT website FROM eta_websites WHERE client=? AND company_number=?",
                            (cfg.slug, number)).fetchone()
        website = site["website"] if site else None
        domain = website.split("://", 1)[-1].split("/")[0].removeprefix("www.") if website else None
        prev = conn.execute("SELECT * FROM eta_contacts WHERE client=? AND company_number=?",
                            (cfg.slug, number)).fetchone()
        person = leader(conn, cfg.slug, number)
        contact = dict(prev) if prev else {"person": person and person["name"], "title": person and person["role"],
                                           "email": None, "email_status": None, "address": None, "phone": None}
        sources = []
        if not prev:
            ein = number[3:] if len(number) == 12 else None          # US-<9-digit EIN>
            if ein:
                contact["address"], contact["phone"] = filing_address(ein, years)
                sources.append("Form 5500 (address, phone)")
            if find_emails and person and domain and fe is not None:
                email, status, credits = find_email(conn, cfg, fe, number, person, domain)
                out["credits"] += credits
                contact["email"], contact["email_status"] = (email, status) if status in ACCEPT else (None, status)
                sources.append("FullEnrich (work email)")
            conn.execute("INSERT OR REPLACE INTO eta_contacts(client, company_number, person, title, email, email_status,"
                         " address, phone, sources, prepared_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (cfg.slug, number, contact["person"], contact["title"], contact["email"],
                          contact["email_status"], contact["address"], contact["phone"],
                          json.dumps(sources + ([f"leader: {person['basis']}"] if person else [])), db.now_iso()))
            conn.commit()
        email, letter = draft(company, contact, metrics, website, today)
        slug = re.sub(r"[^a-z0-9]+", "-", company["name"].lower()).strip("-")[:50]
        path = out_dir / f"{slug}.md"
        path.write_text("\n".join([
            f"# Outreach draft: {company['name']}", "",
            "Status: **draft, not sent.** Fill the {{...}} lines, edit freely, then tell Claude how to send.", "",
            "| | |", "|---|---|",
            f"| To | {contact['person'] or 'unknown'} ({contact['title'] or '-'}) |",
            f"| Work email | {contact['email'] or 'not found'}{' (' + contact['email_status'] + ')' if contact['email_status'] else ''} |",
            f"| Mailing address | {contact['address'] or 'unknown'} |",
            f"| Phone | {contact['phone'] or 'unknown'} |",
            f"| Website | {website or '-'} |", "",
            "## Email", "", "```", email.strip(), "```", "",
            "## Letter (by post, for owners who do not answer email)", "", "```", letter.strip(), "```", ""]),
            encoding="utf-8")
        out["companies"] += 1
        out["emails"] += bool(contact["email"])
        out["addresses"] += bool(contact["address"])
        out["files"].append(str(path))
    return out
