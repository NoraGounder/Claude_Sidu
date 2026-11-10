"""Quailworks as its own client (clients/quailworks/), with synthetic data only (no network).

Also guards The Marble Jar: the per-client settings added for Quailworks must leave its prompts and
rules exactly as they were, and the two clients must never see each other's rows.
"""

import json
import shutil

import pytest
from test_l2_prefilter import FakeFetcher

from gtm import db, signals
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l1_discover, l2_jev, l2_prefilter, l3_contacts, l5_copy, l7_handoff
from gtm.sources.hubspot import HubSpotClient, HubSpotError
from gtm.sources.jev import JevClient, check_policy

QW, TMJ = "quailworks", "the-marble-jar"

# The Marble Jar's prompts as they were before they became per-client settings (2026-11-10).
TMJ_NOT_A_BUYER = ("Is this organisation clearly NOT a commercial company that could buy process "
                   "automation? Not a buyer: trade associations, unions, foundations, media and "
                   "magazines, schools and training bodies, government bodies and port authorities, "
                   "software or IT companies, consultancies, staffing agencies, and companies that "
                   "sell the same kind of service as the seller (see seller_context).")
TMJ_TITLE = ('Is the job title "Crediteurenadministrateur" manual administrative work: invoices, accounts '
             "payable or receivable, order entry or processing, data entry, back office, or "
             "administrative planning support? Drivers, warehouse staff, engineers, technicians, "
             "sales, IT, HR, controllers and managers are not.")
TMJ_CONTACT = ('Would a person with the job title "CFO" at this company decide on, or '
               "strongly influence, buying automation of operations and finance admin processes?")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    for slug in (QW, TMJ):
        shutil.copytree(REPO_ROOT / "clients" / slug, clients / slug, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    return clients


# ---------- configuration ----------

def test_quailworks_config_loads_and_follows_the_jev_policy(env):
    cfg = load_client(QW)
    check_policy(cfg.ai)
    assert cfg.icp.allowed_countries == ["US"]
    assert "themarblejar.io" in cfg.icp.exclusions.domains
    plans = l1_discover.plan(cfg, None, None)
    assert [p.segment.name for p in plans] == ["automation_us", "industrial_software_us", "engineering_services_us"]
    assert round(sum(p.est_cost for p in plans), 2) == 3.60          # inside Apify's free $5 a month
    software = plans[1].actor_input
    assert software["industryIds"] == ["4"] and software["searchQuery"] == "manufacturing"
    assert software["companySize"] == ["11-50", "51-200"] and software["locations"] == ["United States"]


def test_marble_jar_prompts_and_rules_are_unchanged(env):
    cfg = load_client(TMJ)
    item = {"name": "Voorbeeld BV", "industry": "Wholesale", "country": "NL", "employee_range": "51-200",
            "home_title": "", "home_excerpt": "", "job_titles": ["Crediteurenadministrateur"]}
    _, questions, _ = l2_jev.build_request(cfg, item)
    assert questions["not_a_buyer"]["instructions"] == TMJ_NOT_A_BUYER
    assert questions["not_a_buyer"]["criteria"] == {"true": "Not a possible buyer (one of the listed types)",
                                                    "false": "A commercial operating company that could buy"}
    assert questions["title_0"]["instructions"] == TMJ_TITLE
    assert questions["title_0"]["criteria"] == {"true": "Manual administrative work", "false": "Any other kind of role"}
    _, cq = l3_contacts.relevance_request({"name": "Voorbeeld BV"}, [{"title": "CFO"}], cfg.icp.offer_summary,
                                          None, cfg.ai.get("contact_question"))
    assert cq["c0"]["instructions"] == TMJ_CONTACT
    assert signals.rules_for(cfg.scoring) is signals.DEFAULT_RULES
    assert l2_prefilter.job_signal(cfg) == "admin_job_ad"
    seq = l5_copy.load_sequence(cfg)
    assert l5_copy.supported_hooks(seq, {"job_title": 1, "erp": 1}) == ["admin_job_ad", "erp_mention", "generic"]
    assert l5_copy.named_facts(seq) == l5_copy.DEFAULT_NAMED_FACTS


# ---------- Layer 2 ----------

HOME = """<html lang="en"><head><title>Acme Robotics</title></head><body>
<p>We build robotic welding cells for manufacturers across the Midwest. Our cells integrate with
Salesforce and every major PLC brand. Visit us at IMTS 2026, booth #1234. Request a quote today.</p>
<a href="/careers">Careers</a></body></html>"""
CAREERS = """<html lang="en"><body><h1>Open positions</h1>
<a href="/careers/jobs/sales-development-representative">Sales Development Representative</a>
<a href="/careers/jobs/field-service-engineer">Field Service Engineer</a></body></html>"""
JOB = """<html lang="en"><body><h1>Sales Development Representative</h1>
<p>You will research and prospect new accounts and log every touch in HubSpot.</p></body></html>"""
SITE = {"https://acme-robotics.example": HOME,
        "https://acme-robotics.example/careers": CAREERS,
        "https://acme-robotics.example/careers/jobs/sales-development-representative": JOB}


def _account(conn, client, name, website, segments, rng="51-200", country="US", status="qualified_l1"):
    cur = conn.execute(
        "INSERT INTO accounts(client, name, website, domain, country, employee_range, segments, source, status,"
        " first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (client, name, website, website.split("//")[-1] if website else None, country, rng,
         json.dumps(segments), "test", status, "t", "t"))
    return cur.lastrowid


def test_quailworks_signals_scoring_and_tier(env):
    cfg = load_client(QW)
    conn = db.connect()
    acc = _account(conn, QW, "Acme Robotics Inc.", "https://acme-robotics.example", ["automation_us"])
    conn.commit()
    l2_prefilter.run(cfg, conn, workers=1, fetcher_factory=lambda: FakeFetcher(SITE))
    s = conn.execute("SELECT fit, signal, tier, breakdown FROM l2_scores WHERE account_id=?", (acc,)).fetchone()
    # fit: in range 30 + sweet spot 10 + automation 25 + US 15 + site 5 = 85
    # signals: sales job ad 35 + trade show 15 + sales tool in the job ad 10 + request a quote 10 = 70
    assert (s["fit"], s["signal"], s["tier"]) == (85, 70, "tier_1")
    ev = {(r["signal"], r["label"]) for r in conn.execute("SELECT signal, label FROM evidence WHERE account_id=?", (acc,))}
    assert ("sales_job_ad", "sales development representative") in ev
    assert ("trade_show", "IMTS") in ev and ("channel_sales", "request a quote") in ev
    assert ("sales_stack", "HubSpot") in ev                 # named in the job ad
    assert ("sales_stack", "Salesforce") not in ev          # homepage product text does not count


def test_quailworks_jev_questions_and_job_title_evidence(env):
    cfg = load_client(QW)
    item = {"name": "Acme Software", "industry": "Software Development", "country": "US", "employee_range": "11-50",
            "home_title": "", "home_excerpt": "", "job_titles": ["Inside Sales Representative"]}
    _, q, _ = l2_jev.build_request(cfg, item)
    assert "Software, engineering, automation and industrial companies" in q["not_a_buyer"]["instructions"]
    assert q["not_a_buyer"]["criteria"]["false"] == "A company that sells to other businesses and could buy"
    assert q["title_0"]["instructions"].startswith('Is the job title "Inside Sales Representative" a sales role')
    assert "manufacturers and industrial operators" in q["icp_fit"]["instructions"]
    ev = l2_prefilter.jev_evidence(cfg, None, {"titles": {"Inside Sales Representative": 0.9, "Welder": 0.1}})
    assert [(e.signal, e.label) for e in ev] == [("sales_job_ad", "job title: Inside Sales Representative")]


# ---------- Layer 5 ----------

class StubJev:
    def __init__(self, unsupported=0.05):
        self.headers, self.bodies, self.unsupported = {}, [], unsupported

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        answers = {}
        for key, q in json["questions"].items():
            if q["type"] == "choice":
                first = list(q["criteria"])[0]
                answers[key] = {"type": "choice", "choice": first, "probabilities": {first: 0.7}}
            else:
                answers[key] = {"type": "noul", "noul": self.unsupported}

        class R:
            status_code, text = 200, ""

            @staticmethod
            def json():
                return {"model": "typesafe/jev-1.14-20261014", "answers": answers,
                        "usage": {"input_tokens": 400, "output_tokens": 8, "cost": 0.00002}}
        return R()


def _qw_contact(conn):
    acc = _account(conn, QW, "Acme Robotics Inc.", "https://acme-robotics.example", ["automation_us"], status="tier_1")
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, careers_url, job_titles,"
                 " scored_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (acc, 85, 70, "tier_1", 1, 0, "https://acme-robotics.example/careers",
                  json.dumps(["Sales Development Representative", "Field Service Engineer"]), "t"))
    for signal, label in (("sales_job_ad", "sales development representative"), ("sales_stack", "HubSpot")):
        conn.execute("INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
                     (acc, "L2", signal, label, "https://acme-robotics.example/careers/jobs/x", "…", "t"))
    conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, title, persona, status,"
                 " status_reason, email, email_status, data_source, created_at, updated_at)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (QW, acc, "p1", "JORDAN", "Lee", "VP Sales", "sales_leader", "held", "sender_consent_pending",
                  "jordan@acme-robotics.example", "DELIVERABLE", "FullEnrich", "t", "t"))
    conn.commit()
    return acc


def test_quailworks_draft_from_facts_then_approval(env):
    cfg = load_client(QW)
    conn = db.connect()
    _qw_contact(conn)
    stub = StubJev()
    t = l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=stub))
    assert t["drafted"] == 1 and t["preview"] == 1                  # no private/sender.yaml yet
    d = conn.execute("SELECT * FROM drafts").fetchone()
    steps, facts = json.loads(d["steps_json"]), json.loads(d["facts_json"])
    assert (d["hook"], d["process"], d["language"]) == ("sales_job_ad", "outbound", "en")
    assert facts["job_title"]["value"] == "sales development representative" and facts["stack"]["value"] == "HubSpot"
    assert d["subject"] == "your sales development representative opening"
    body = steps[0]["body"]
    assert "I saw the sales development representative opening at Acme Robotics." in body   # "Inc." dropped
    assert body.splitlines()[0].endswith("Jordan,")
    assert "Quailworks sp. z o.o., ul. Mikołaja Reja 34, 26-225 Gowarczów, Poland." in body
    assert "http" not in body and not any("{" in s["body"] for s in steps)    # no link, no unfilled placeholder
    # One process, so Jev is asked only for the angle and the fact check; it never sees names or the client.
    asked = [k for b in stub.bodies for k in b["questions"]]
    assert "process" not in asked and "angle" in asked and "unsupported_claim" in asked
    sent = json.dumps(stub.bodies)
    assert "Jordan" not in sent and "@" not in sent and "Marble" not in sent
    assert "Quailworks's own offer" in sent

    assert l5_copy.auto_approve(cfg, conn)["approved"] == 0          # previews are never approved
    (env / QW / "private").mkdir()
    (env / QW / "private" / "sender.yaml").write_text("first_name: Sam\nfull_name: Sam Example\n")
    l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=StubJev()), redo=True)
    assert l5_copy.auto_approve(cfg, conn)["approved"] == 1
    assert l7_handoff.sender_name(cfg) == "Sam"


def test_banned_phrases_block_automatic_approval(env):
    cfg = load_client(QW)
    conn = db.connect()
    _qw_contact(conn)
    (env / QW / "private").mkdir()
    (env / QW / "private" / "sender.yaml").write_text("first_name: Sam\n")
    l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=StubJev()))
    steps = json.loads(conn.execute("SELECT steps_json FROM drafts").fetchone()[0])
    steps[1]["body"] += "\nWe guarantee results."
    conn.execute("UPDATE drafts SET steps_json=?", (json.dumps(steps),))
    assert l5_copy.auto_approve(cfg, conn) == {"approved": 0, "left_for_review": 1}


# ---------- boundaries between clients ----------

def test_quailworks_never_sees_marble_jar_rows(env):
    qw = load_client(QW)
    conn = db.connect()
    tmj_acc = _account(conn, TMJ, "Voorbeeld Groothandel BV", "https://voorbeeld.example", ["wholesale_nl"],
                       country="NL", status="tier_1")
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at)"
                 " VALUES (?,?,?,?,?,?,?)", (tmj_acc, 90, 60, "tier_1", 1, 1, "t"))
    conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, title, persona, status,"
                 " email, email_status, data_source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (TMJ, tmj_acc, "p9", "Anna", "Jansen", "CFO", "finance", "ready", "anna@voorbeeld.example",
                  "DELIVERABLE", "FullEnrich", "t", "t"))
    conn.commit()
    assert l2_jev.plan(qw, conn).items == []
    assert l3_contacts.plan(qw, conn).accounts == []
    assert l5_copy.draft(qw, conn, jev=JevClient(qw.ai, session=StubJev()))["drafted"] == 0
    # The same company found by Quailworks' own discovery becomes a separate Quailworks row.
    assert db.upsert_account(conn, QW, {"linkedin_url": None, "domain": "voorbeeld.example", "name": "Voorbeeld",
                                        "source": "test", "status": "qualified_l1"}, "automation_us") == "new"


def test_hubspot_token_is_per_client(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "the-marble-jar-portal")
    monkeypatch.delenv("HUBSPOT_TOKEN_QUAILWORKS", raising=False)
    with pytest.raises(HubSpotError, match="HUBSPOT_TOKEN_QUAILWORKS"):
        HubSpotClient(token_env="HUBSPOT_TOKEN_QUAILWORKS")      # never falls back to another client's portal


# ---------- title exclusions (both clients) ----------

def test_excluded_titles_stop_at_word_ends(env):
    tmj = load_client(TMJ).icp.personas["exclude_titles"]
    for title in ("Finance Intern", "Intern Operations", "Internship Supply Chain", "Stagiair Finance",
                  "Stagiaire Logistiek", "Managementassistent", "Werkstudent Finance", "Trainee Operations",
                  "Traineeship Finance", "Assistant Controller"):
        assert l3_contacts.title_excluded(title, tmj), title
    for title in ("International Operations Manager", "Internationaal Supply Chain Manager",
                  "Interne Logistiek Manager", "Operations Director"):
        assert l3_contacts.title_excluded(title, tmj) is None, title
    qw = load_client(QW).icp.personas["exclude_titles"]
    assert l3_contacts.title_excluded("International Sales Director", qw) is None
    assert l3_contacts.title_excluded("Sales Development Representative", qw) == "Representative"
