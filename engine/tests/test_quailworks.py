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
    assert cfg.icp.allowed_countries == ["US", "GB"]
    assert "themarblejar.io" in cfg.icp.exclusions.domains
    plans = l1_discover.plan(cfg, None, None)
    # Segments after the review of 2026-11-11 (decisions.md Q29): software, robotics and automation.
    assert [p.segment.name for p in plans] == ["mfg_software_us", "industrial_software_aero_us",
                                               "industrial_ai_us", "robotics_automation_us",
                                               "digital_twin_us", "machine_vision_us", "industrial_software_uk"]
    assert round(sum(p.est_cost for p in plans), 2) == 7.80          # inside the $15 Apify cap
    assert plans[3].actor_input["industryIds"] == ["147", "3247", "3248"]
    assert plans[1].actor_input["searchQuery"] == "aerospace software"      # two-word phrases (live test)
    assert plans[6].actor_input["locations"] == ["United Kingdom"]
    software = plans[0].actor_input
    assert software["industryIds"] == ["4"] and software["searchQuery"] == "manufacturing software"
    assert software["companySize"] == ["11-50", "51-200", "201-500", "501-1000"] and software["locations"] == ["United States"]


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
Salesforce and every major PLC brand. AS9100D certified. Backed by Lux Capital. Visit us at IMTS 2026, booth #1234. Request a quote today.</p>
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
    acc = _account(conn, QW, "Acme Robotics Inc.", "https://acme-robotics.example", ["robotics_automation_us"])
    conn.commit()
    l2_prefilter.run(cfg, conn, workers=1, fetcher_factory=lambda: FakeFetcher(SITE))
    s = conn.execute("SELECT fit, signal, tier, breakdown FROM l2_scores WHERE account_id=?", (acc,)).fetchone()
    # fit: in range 30 + sweet spot 10 + robotics and automation 25 + US 15 + site 5 = 85
    # signals: sales job ad 35 + trade show 15 + sales tool in the job ad 10 + request a quote 10
    #          + AS9100 certification 10 + venture-backed 15 = 95
    assert (s["fit"], s["signal"], s["tier"]) == (85, 95, "tier_1")
    ev = {(r["signal"], r["label"]) for r in conn.execute("SELECT signal, label FROM evidence WHERE account_id=?", (acc,))}
    assert ("sales_job_ad", "sales development representative") in ev
    assert ("trade_show", "IMTS") in ev and ("channel_sales", "request a quote") in ev
    assert ("trade_show", "visit us at our booth") in ev and ("supplier_certification", "AS9100") in ev
    assert ("venture_backed", "backed by investors") in ev
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
    assert "high-value products" in q["icp_fit"]["instructions"] and "Poor fit: build-to-print" in q["icp_fit"]["instructions"]
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
    acc = _account(conn, QW, "Acme Robotics Inc.", "https://acme-robotics.example", ["robotics_automation_us"], status="tier_1")
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
    # One process and angle: priority, so Jev only fact-checks; it never sees names or the client.
    asked = [k for b in stub.bodies for k in b["questions"]]
    assert asked == ["unsupported_claim"]
    assert "Open job listed on their careers page: sales development representative" in json.dumps(stub.bodies)
    assert "Sales tool named in one of their job ads: HubSpot" in json.dumps(stub.bodies)
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
                                        "source": "test", "status": "qualified_l1"}, "robotics_automation_us") == "new"


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


def test_poor_jev_icp_fit_caps_quailworks_at_tier_3_but_not_the_marble_jar(env):
    qw, tmj = load_client(QW), load_client(TMJ)
    assert l2_prefilter.tier_for(qw, 85, 70, None, 0.4) == "tier_3"      # poor fit: no contacts bought
    assert l2_prefilter.tier_for(qw, 85, 70, None, 1.2) == "tier_1"
    assert l2_prefilter.tier_for(qw, 85, 70, None, None) == "tier_1"     # not decided by Jev yet
    assert l2_prefilter.tier_for(tmj, 85, 70, None, 0.4) == "tier_1"     # The Marble Jar unchanged


def test_quailworks_skips_people_the_send_gate_would_hold_back(env):
    qw, tmj = load_client(QW), load_client(TMJ)

    def person(pid, title, country):
        return {"id": pid, "first_name": "A", "last_name": "B", "employment": {"current": {"title": title}},
                "location": {"country_code": country}}
    people = [person("1", "VP Sales", "US"), person("2", "Business Development Director", "PL"),
              person("3", "Head of Sales", "GB"), person("4", "Sales Director", None)]
    acc = {"employee_range": "51-200"}
    kept = [p["person_id"] for p in l3_contacts.screen(qw, acc, people)]
    assert kept == ["1", "3", "4"]                     # Poland dropped; unknown country kept for the gate
    assert l3_contacts.sendable_countries(tmj) is None  # The Marble Jar unchanged (not opted in)


def test_quailworks_quotes_clean_role_names_and_trims_taglines(env):
    cfg = load_client(QW)
    seq = l5_copy.load_sequence(cfg)
    conn = db.connect()
    glued = "Account Executive We’re looking for a mid-level generalist to join our team. U.S. - Remote Full-time"
    for titles, want in ((["Field Service Engineer", glued], "account executive"),
                         (["销售工程师（Sales engineer"], "sales engineer"),
                         (["Sr Director, Business Development (Government/Defense)"], "business development director"),
                         (["Welder"], None)):
        acc = _account(conn, QW, "Acme", "https://acme.example", ["robotics_automation_us"], status="tier_1")
        conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, careers_url, job_titles,"
                     " scored_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (acc, 85, 35, "tier_1", 1, 0, "https://acme.example/careers", json.dumps(titles), "t"))
        for t in titles:   # Jev 1.14 confirmed every title as a sales role
            conn.execute("INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
                         (acc, "L2", "sales_job_ad", f"job title: {t}", "https://acme.example/careers", t, "t"))
        facts = l5_copy.facts_for(conn, {"id": acc}, seq, signals.rules_for(cfg.scoring), "sales_job_ad")
        assert facts.get("job_title", {}).get("value") == want, titles
    cut = seq["company_name_cut"]
    assert l5_copy.clean_company("Vimachem - IIoT Pharma 4.0 AI Platform", seq["company_suffixes"], cut) == "Vimachem"
    assert l5_copy.clean_company("Infor XA | Manufacturing Software", seq["company_suffixes"], cut) == "Infor XA"
    assert l5_copy.clean_company("Acme Robotics, Inc.", seq["company_suffixes"], cut) == "Acme Robotics"



def test_one_smartlead_account_keeps_each_sending_domain_with_one_client(env):
    from gtm.layers import l6_send

    # The real config: The Marble Jar's and Quailworks' sending domains never overlap.
    qw, tmj = load_client(QW), load_client(TMJ)
    assert l6_send.shared_domains(qw) == [] and l6_send.shared_domains(tmj) == []
    # A domain listed for both clients stops push for either of them before Smartlead is called.
    sending = env / QW / "sending.yaml"
    text = sending.read_text()
    assert "mailbox_domains: [getquailworks.com, quailworksforward.com]" in text
    sending.write_text(text.replace("mailbox_domains: [getquailworks.com,", "mailbox_domains: [GetMarbleJar.com, getquailworks.com,"))
    assert l6_send.shared_domains(load_client(QW)) == ["getmarblejar.com"]
    assert l6_send.shared_domains(load_client(TMJ)) == ["getmarblejar.com"]
    with pytest.raises(RuntimeError, match="getmarblejar.com"):
        l6_send.push(load_client(TMJ), db.connect(), sl=object())


# ---------- job boards and checked job-ad matches (audit 2026-11-11) ----------

BOARD_HOME = """<html lang="en"><head><title>Acme Robotics</title></head><body><p>Robotic welding cells.</p>
<a href="/careers">Careers</a></body></html>"""
BOARD_CAREERS = """<html lang="en"><body><h1>Join us</h1><p>“I love it here.” Dana Lee, Account Executive</p>
<iframe src="https://jobs.ashbyhq.com/acme-robotics/embed"></iframe></body></html>"""
ASHBY_FEED = {"jobs": [
    {"title": "Welding Engineer", "location": "Detroit", "address": {"postalAddress": {"addressCountry": "United States"}}},
    {"title": "Sales Development Representative", "location": "Austin", "isListed": True,
     "address": {"postalAddress": {"addressCountry": "United States"}}},
    {"title": "Account Executive", "location": "Chennai", "address": {"postalAddress": {"addressCountry": "India"}}},
    {"title": "Hidden Role", "location": "Austin", "isListed": False}]}


class BoardFetcher(FakeFetcher):
    def __init__(self, pages, feeds):
        super().__init__(pages)
        self.feeds = feeds

    def get_json(self, url):
        self.requested.append(url)
        return self.feeds.get(url)


def test_job_board_feed_gives_exact_titles_only_when_the_client_asks(env):
    from gtm import jobboards
    from gtm.crawl import crawl_site

    board = jobboards.find_board(["https://acme.example/about", "https://boards.greenhouse.io/embed/job_board/js?for=acme"])
    assert (board.name, board.slug) == ("greenhouse", "acme") and board.feed.endswith("/v1/boards/acme/jobs")
    assert jobboards.find_board(["https://jobs.lever.co/acme-labs/123"]).feed == "https://api.lever.co/v0/postings/acme-labs?mode=json"
    assert jobboards.find_board(["https://www.linkedin.com/company/acme"]) is None
    lever = jobboards.parse_feed("lever", [{"text": "BDR", "categories": {"location": "London"}, "country": "GB"}])
    assert lever == [{"title": "BDR", "location": "London", "country": "GB"}]
    gh = jobboards.parse_feed("greenhouse", {"jobs": [{"title": "AE ", "location": {"name": "Boston, MA"}}]})
    assert jobboards.titles(gh, ["US", "GB"]) == ["AE (Boston, MA)"]        # no stated country: kept

    pages = {"https://acme-robotics.example": BOARD_HOME, "https://acme-robotics.example/careers": BOARD_CAREERS}
    feeds = {"https://api.ashbyhq.com/posting-api/job-board/acme-robotics": ASHBY_FEED}
    plain = crawl_site(BoardFetcher(pages, feeds), "https://acme-robotics.example")
    assert plain.job_titles == [] and plain.board_url == ""                 # default: feeds are not read
    cfg = load_client(QW)
    assert load_client(TMJ).scoring.get("job_boards") is None
    site = crawl_site(BoardFetcher(pages, feeds), "https://acme-robotics.example", job_boards=cfg.scoring["job_boards"])
    assert site.board_url == "https://jobs.ashbyhq.com/acme-robotics"
    # the role in India and the unlisted role are left out; the location stays in the title
    assert site.job_titles == ["Welding Engineer (Detroit, United States)",
                               "Sales Development Representative (Austin, United States)"]
    assert l2_prefilter.order_titles(cfg, site.job_titles)[0].startswith("Sales Development Representative")


def test_jev_checks_job_ad_matches_before_they_count_or_are_quoted(env):
    from gtm.crawl import crawl_site
    from gtm.sources.jev import JevResult

    cfg, tmj = load_client(QW), load_client(TMJ)
    conn = db.connect()
    acc = _account(conn, QW, "Acme Robotics", "https://acme-robotics.example", ["robotics_automation_us"])
    conn.commit()
    pages = {"https://acme-robotics.example": BOARD_HOME, "https://acme-robotics.example/careers": BOARD_CAREERS}
    fetch = lambda: FakeFetcher(pages)                                      # noqa: E731
    l2_prefilter.run(cfg, conn, workers=1, fetcher_factory=fetch)
    # Not checked yet: the testimonial's "Account Executive" still counts as a sales job ad (Tier 1).
    assert conn.execute("SELECT tier FROM l2_scores WHERE account_id=?", (acc,)).fetchone()["tier"] == "tier_1"

    item = l2_jev.plan(cfg, conn).items[0]
    assert [e["label"] for e in item["job_evidence"]] == ["account executive"]
    _, questions, keys = l2_jev.build_request(cfg, item)
    assert "Dana Lee, Account Executive" in questions["evidence_0"]["instructions"]
    assert 'open position right now for the role "account executive"' in questions["evidence_0"]["instructions"]
    tmj.ai.pop("job_evidence", None)            # The Marble Jar opted in on 2026-11-11; this is the default
    _, default_questions, _ = l2_jev.build_request(tmj, item)
    assert "evidence_0" not in default_questions                           # without the setting: no check

    def decide(p):
        answers = {"not_a_buyer": {"noul": 0.02}, "icp_fit": {"score": 1.8}, "evidence_0": {"noul": p}}
        l2_jev._save_decision(conn, acc, JevResult(answers, "typesafe/jev-1.14-test", 1, 1, 0.0, 1, None), keys,
                              item["job_evidence"])
        conn.commit()
        l2_prefilter.run(cfg, conn, workers=1, fetcher_factory=fetch, account_ids=[acc])
        tier = conn.execute("SELECT tier FROM l2_scores WHERE account_id=?", (acc,)).fetchone()["tier"]
        facts = l5_copy.facts_for(conn, {"id": acc}, l5_copy.load_sequence(cfg), signals.rules_for(cfg.scoring),
                                  "sales_job_ad", l2_prefilter.evidence_threshold(cfg))
        return tier, facts.get("job_title", {}).get("value")

    # Jev: a testimonial, not an open role. The signal goes, and so does Tier 1; nothing is quoted.
    assert decide(0.05) == ("tier_3", None)
    # A later decision that does not ask about the match again keeps the rejection.
    l2_jev._save_decision(conn, acc, JevResult({"not_a_buyer": {"noul": 0.02}, "icp_fit": {"score": 1.8}},
                                               "typesafe/jev-1.14-test", 1, 1, 0.0, 1, None), {}, [])
    assert json.loads(conn.execute("SELECT checks_json FROM jev_decisions WHERE account_id=?", (acc,)).fetchone()[0])
    # Jev: an open role. It counts again and the email may name the role.
    assert decide(0.93) == ("tier_1", "account executive")
    # Without the check (The Marble Jar's default), a word match is never quoted.
    facts = l5_copy.facts_for(conn, {"id": acc}, l5_copy.load_sequence(cfg), signals.rules_for(cfg.scoring), "sales_job_ad")
    assert "job_title" not in facts


def test_several_matches_per_label_only_for_clients_that_ask(env):
    from gtm.crawl import crawl_site

    careers = ("<html><body><p>“Great team.” Sam, Account Executive</p>" + "<p>filler text here.</p>" * 30 +
               "<h2>Open roles</h2><p>Account Executive, Chicago. Apply now.</p></body></html>")
    pages = {"https://x.example": '<html><body>Robots. <a href="/careers">Careers</a></body></html>',
             "https://x.example/careers": careers}
    site = crawl_site(FakeFetcher(pages), "https://x.example")
    qw = signals.extract(site, signals.rules_for(load_client(QW).scoring))
    assert [e.label for e in qw if e.signal == "sales_job_ad"] == ["account executive", "account executive"]
    default = signals.SignalRules({"sales_job_ad": [("account executive", r"account\s+executive")]},
                                  frozenset({"sales_job_ad"}), frozenset())
    assert len(signals.extract(site, default)) == 1                         # the default keeps the first match


def test_unconfirmed_emails_wait_for_verification_only_for_quailworks(env):
    from datetime import datetime, timezone

    from gtm.layers import l4_gate

    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    conn = db.connect()
    for client, domain in ((QW, "acme.example"), (TMJ, "voorbeeld.example")):
        acc = _account(conn, client, "Acme", f"https://{domain}", [], status="tier_1")
        conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at)"
                     " VALUES (?,?,?,?,?,?,?)", (acc, 85, 35, "tier_1", 1, 0, "t"))
        for first, status in (("sure", "DELIVERABLE"), ("maybe", "HIGH_PROBABILITY"), ("dead", "HIGH_PROBABILITY")):
            conn.execute(
                "INSERT INTO contacts(client, account_id, person_id, first_name, last_name, country, status, email,"
                " email_status, email_source, data_source, verified_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (client, acc, f"{client}-{first}", first, "X", "US" if client == QW else "NL", "email_found",
                 f"{first}@{domain}", status, "FullEnrich", "FullEnrich people search", now.isoformat(),
                 now.isoformat(), now.isoformat()))
    conn.commit()

    def statuses(client):
        return {r["first_name"]: (r["status"], r["status_reason"])
                for r in conn.execute("SELECT * FROM contacts WHERE client=?", (client,))}

    l4_gate.run(load_client(TMJ), conn, now=now)
    assert {s for s, _ in statuses(TMJ).values()} == {"ready"}             # The Marble Jar: unchanged
    cfg = load_client(QW)
    l4_gate.run(cfg, conn, now=now)
    qw = statuses(QW)
    # no finder is trusted alone (decisions.md Q39): every address waits for verification
    assert qw["sure"] == qw["maybe"] == qw["dead"] == ("held", "unverified_email:run gate --recheck")

    class StubMV:
        checked = []

        def verify(self, email):
            self.checked.append(email)
            return {"result": "invalid" if email.startswith("dead") else "ok", "role": False, "free": False}

    l4_gate.run(cfg, conn, recheck=True, mv=StubMV(), now=now)
    qw = statuses(QW)
    assert sorted(StubMV.checked) == ["dead@acme.example", "maybe@acme.example", "sure@acme.example"]
    assert qw["sure"] == qw["maybe"] == ("held", "sender_consent_pending")   # only the launch consent is missing
    assert qw["dead"] == ("rejected_l4", "email_status:INVALID")
    l4_gate.run(cfg, conn, recheck=True, mv=StubMV(), now=now)
    assert len(StubMV.checked) == 3                                         # verified once, not again


# ---------- conversion pass (decisions.md Q37) ----------

def test_best_companies_are_uploaded_first_only_when_the_client_asks(env, monkeypatch):
    from gtm.layers import l6_send

    conn = db.connect()
    for slug in (QW, TMJ):
        (env / slug / "private").mkdir()
        (env / slug / "private" / "sender.yaml").write_text("first_name: Sam\nfull_name: Sam Example\n")
        client = env / slug / "client.yaml"
        client.write_text(client.read_text().replace("consent_to_send_in_name: pending", "consent_to_send_in_name: granted"))
        country = "US" if slug == QW else "NL"
        # inserted weakest first: upload order must not follow insertion order for Quailworks
        for name, tier, signal in (("Weak Co", "tier_2", 20), ("Mid Co", "tier_1", 35), ("Best Co", "tier_1", 60)):
            acc = _account(conn, slug, name, f"https://{name.split()[0].lower()}-{slug}.example", [], country=country, status=tier)
            conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at)"
                         " VALUES (?,?,?,?,?,?,?)", (acc, 85, signal, tier, 1, 0, "t"))
            cur = conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, status, email,"
                               " email_status, data_source, rank, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (slug, acc, f"{slug}-{name}", name.split()[0], "T", "ready",
                                f"x@{name.split()[0].lower()}-{slug}.example", "DELIVERABLE", "FullEnrich", 1, "t", "t"))
            conn.execute("INSERT INTO drafts(client, contact_id, language, hook, process, subject, steps_json, facts_json,"
                         " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (slug, cur.lastrowid, "en", "generic", "outbound", "s", json.dumps([{"day": 0, "body": "b"}]),
                          "{}", "approved", "t", "t"))
    conn.commit()
    qw = l6_send.plan_push(load_client(QW), conn)
    assert [lead["first_name"] for lead in qw.eligible["us"]] == ["Best", "Mid", "Weak"]
    tmj = l6_send.plan_push(load_client(TMJ), conn)
    assert [lead["first_name"] for lead in next(iter(tmj.eligible.values()))] == ["Weak", "Mid", "Best"]   # unchanged


def test_email_one_is_short_and_asks_one_thing(env):
    cfg = load_client(QW)
    seq = l5_copy.load_sequence(cfg)
    contact = {"id": 7, "first_name": "Dana", "title": "VP Sales", "persona": "sales_leader"}
    account = {"name": "Acme Robotics, Inc.", "industry": "Robotics"}
    sender, notice = {"first_name": "Sam"}, "Source and opt-out notice."
    _, job = l5_copy.render(seq, "en", "sales_job_ad", "outbound", {"job_title": {"value": "account executive"}},
                            contact, account, sender, notice)
    _, plain = l5_copy.render(seq, "en", "generic", "outbound", {}, contact, account, sender, notice)
    first = job[0]["body"]
    assert "I saw the account executive opening at Acme Robotics." in first
    assert "It could be that person's first list." in first and "It could be that person's first list." not in plain[0]["body"]
    for body in (first, plain[0]["body"]):
        assert body.count("?") <= 2 and "{" not in body and "No call needed." in body
        assert len(body.replace(notice, "").split()) <= 100          # short enough to read on a phone
    assert "12 qualified meetings" in job[1]["body"] and len(job[1]["body"].split()) <= 115
    assert not [p for p in seq["banned_phrases"] for s in job if p in s["body"].lower()]


def test_signal_sample_lists_companies_with_sources_and_stores_no_accounts(env):
    from gtm import sample
    from gtm.sources.apify import RunResult

    cfg = load_client(QW)
    conn = db.connect()
    actor_input, est = sample.plan(cfg, "contract manufacturing", ["135"], ["United States"])
    assert actor_input["maxItems"] == 60 and actor_input["searchQuery"] == "contract manufacturing" and est == 0.24

    def company(name, site):
        return {"name": name, "website": site, "employeeCountRange": {"start": 51, "end": 200},
                "locations": [{"headquarter": True, "country": "US", "city": "Detroit"}]}

    class Client:
        def run_actor(self, actor, payload):
            return RunResult([company("Hiring Works", "https://hiring.example"),
                              company("Growing Plant", "https://growing.example"),
                              company("Quiet Co", "https://quiet.example")], "run1", "SUCCEEDED", 0.0)

    pages = {
        "https://hiring.example": '<html><body>Machined parts. <a href="/careers">Careers</a></body></html>',
        "https://hiring.example/careers": '<html><body><a href="/careers/jobs/controls-engineer">Controls Engineer</a></body></html>',
        "https://hiring.example/careers/jobs/controls-engineer": "<html><body><h1>Controls Engineer</h1></body></html>",
        "https://growing.example": "<html><body>We are opening a new production line in Ohio.</body></html>",
        "https://quiet.example": "<html><body>Quality parts since 1970.</body></html>",
    }
    r = sample.run(cfg, conn, "Acme Robotics", actor_input, est, roles=["controls engineer"], client=Client(),
                   fetcher_factory=lambda: FakeFetcher(pages), workers=1)
    text = r["path"].read_text()
    assert (r["read"], r["with_signal"], r["listed"]) == (3, 2, 2) and r["path"].name == "acme-robotics.md"
    assert text.index("Hiring Works") < text.index("Growing Plant") and "Quiet Co" not in text
    assert 'Hiring: "Controls Engineer" (https://hiring.example/careers)' in text
    assert "Expanding:" in text and "(https://growing.example)" in text
    # the prospect's market is not Quailworks' pipeline: only the run is logged
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
    run = conn.execute("SELECT layer, vendor, label, status, actual_cost FROM runs").fetchone()
    assert tuple(run) == ("SAMPLE", "apify", "sample:Acme Robotics", "succeeded", 0.012)


# ---------- BlitzAPI: discovery by hiring signal and first email source (decisions.md Q39) ----------

class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


class BlitzSession:
    """Stands in for requests.Session: answers BlitzAPI's three endpoints from canned data."""

    def __init__(self, companies, emails):
        self.headers, self.calls, self.companies, self.emails = {}, [], companies, emails

    def post(self, url, json=None, timeout=None):
        self.calls.append((url.rsplit("/v2", 1)[1], json))
        usage = {"records_used": 1, "records_remaining": 990}
        if url.endswith("/company/tam-by-jobs"):
            start = int(json.get("cursor") or 0)
            page = self.companies[start:start + json["max_results"]]
            nxt = str(start + len(page)) if start + len(page) < len(self.companies) else None
            return _Resp({"results": page, "cursor": nxt, "fair_usage": usage})
        if url.endswith("/enrichment/email"):
            email = self.emails.get(json["person_linkedin_url"])
            return _Resp({"found": bool(email), "email": email, "fair_usage": usage})
        return _Resp({"error": "unknown"}, 404)


def _blitz_company(name, domain, country="US", size="51-200"):
    return {"company": {"linkedin_url": f"https://www.linkedin.com/company/{domain.split('.')[0]}", "linkedin_id": 1,
                        "name": name, "about": "Robots.", "industry": "Robotics Engineering", "size": size,
                        "employees_on_linkedin": 120, "hq": {"city": "Austin", "country_code": country},
                        "domain": domain, "website": f"https://www.{domain}"}, "matched_jobs": 2}


def test_discovery_by_hiring_signal_stores_accounts_within_the_record_allowance(env):
    from gtm import budget
    from gtm.layers import l1_hiring
    from gtm.sources.blitz import BlitzClient

    cfg = load_client(QW)
    conn = db.connect()
    plans = l1_hiring.plan(cfg, ["hiring_robotics_us"], 3)
    assert plans[0].job["date_posted"] == {"last_days": 30} and plans[0].job["location"] == {"country_code": {"include": ["US"]}}
    assert "Robotics Engineering" in plans[0].company["industry"]["include"]
    assert plans[0].company["employee_count"] == {"min": 11, "max": 1000} and plans[0].est_cost == 0
    session = BlitzSession([_blitz_company("Halden Robotics", "halden.example"),
                            _blitz_company("Mega Corp", "mega.example", size="10001+"),
                            _blitz_company("Elsewhere GmbH", "elsewhere.example", country="DE"),
                            _blitz_company("Never Fetched", "never.example")], {})
    res = l1_hiring.run(cfg, conn, plans, client=BlitzClient(api_key="k", session=session))[0]
    assert (res.fetched, res.new, res.qualified) == (3, 3, 1) and set(res.rejected) == {"size_out_of_range", "country"}
    acc = conn.execute("SELECT * FROM accounts WHERE status='qualified_l1'").fetchone()
    assert (acc["name"], acc["domain"], acc["country"], acc["employee_range"]) == ("Halden Robotics", "halden.example", "US", "51-200")
    assert json.loads(acc["segments"]) == ["robotics_automation_us"] and acc["source"] == "blitzapi:companies-hiring:hiring_robotics_us"
    assert session.headers["x-api-key"] == "k"
    assert l1_hiring.records_used(conn, QW) == 3
    # the month's record allowance is a hard stop (limits.yaml blitzapi_records: 1000)
    with pytest.raises(budget.BudgetExceeded, match="blitzapi"):
        l1_hiring.run(cfg, conn, l1_hiring.plan(cfg, ["hiring_robotics_us"], 998), client=BlitzClient(api_key="k", session=session))
    assert not (env / TMJ / "hiring.yaml").exists()                         # The Marble Jar: not set up


def test_blitzapi_is_tried_first_for_emails_only_when_the_client_asks(env):
    from gtm.sources.blitz import BlitzClient

    cfg = load_client(QW)
    conn = db.connect()
    acc = _account(conn, QW, "Halden Robotics", "https://halden.example", ["robotics_automation_us"], status="tier_1")
    for first in ("known", "unknown"):
        conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, linkedin_url, status,"
                     " data_source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (QW, acc, first, first, "X", f"https://www.linkedin.com/in/{first}", "selected", "FullEnrich people search", "t", "t"))
    conn.commit()
    rows = [dict(r) for r in conn.execute("SELECT * FROM contacts ORDER BY id")]
    session = BlitzSession([], {"https://www.linkedin.com/in/known": "Known@Halden.example"})
    left = l3_contacts.blitz_emails(cfg, conn, rows, BlitzClient(api_key="k", session=session))
    assert [r["first_name"] for r in left] == ["unknown"]                   # goes on to FullEnrich
    got = conn.execute("SELECT status, email, email_status, email_source FROM contacts WHERE first_name='known'").fetchone()
    assert tuple(got) == ("email_found", "known@halden.example", "DELIVERABLE", "BlitzAPI")
    assert conn.execute("SELECT status FROM contacts WHERE first_name='unknown'").fetchone()[0] == "selected"
    # opt-in: Quailworks switched it on for the trial (2026-11-12); The Marble Jar has not
    assert (cfg.scoring["enrichment_policy"].get("email_first"), load_client(TMJ).scoring.get("enrichment_policy", {}).get("email_first")) == ("blitzapi", None)


def test_env_file_is_read_without_overriding_or_printing(tmp_path, monkeypatch, capsys):
    from gtm import cli

    env_file = tmp_path / ".env"
    env_file.write_text("# keys\nMILLIONVERIFIER_API_KEY=abc123   # Layer 4\nSMARTLEAD_API_KEY='from-file'\nEMPTY=\nnot a line\n")
    monkeypatch.delenv("MILLIONVERIFIER_API_KEY", raising=False)
    monkeypatch.setenv("SMARTLEAD_API_KEY", "already-set")
    assert cli.load_env_file(env_file) == 1
    import os
    assert os.environ["MILLIONVERIFIER_API_KEY"] == "abc123" and os.environ["SMARTLEAD_API_KEY"] == "already-set"
    assert "EMPTY" not in os.environ and capsys.readouterr().out == ""
    assert cli.load_env_file(tmp_path / "missing.env") == 0


def test_funnel_counts_one_client_and_suppression_is_checked_before_paid_lookups(env):
    from gtm import funnel

    conn = db.connect()
    for slug in (QW, TMJ):
        acc = _account(conn, slug, f"{slug} Co", f"https://{slug}.example", [], status="tier_1")
        conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at) VALUES (?,?,?,?,?,?,?)",
                     (acc, 85, 35, "tier_1", 1, 0, "t"))
        conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, status, status_reason, email,"
                     " email_status, data_source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (slug, acc, slug, "A", "B", "held", "sender_consent_pending", f"a@{slug}.example", "DELIVERABLE", "x", "t", "t"))
        conn.execute("INSERT INTO runs(client, layer, vendor, label, started_at, status, est_cost, actual_cost) VALUES (?,?,?,?,?,?,?,?)",
                     (slug, "L3-email", "fullenrich", "x", "t", "succeeded", 1.0, 2.0 if slug == QW else 50.0))
    blocked = _account(conn, QW, "Blocked Robotics", "https://blocked.example", [], status="tier_1")
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at) VALUES (?,?,?,?,?,?,?)",
                 (blocked, 85, 35, "tier_1", 1, 0, "t"))
    db.add_suppression(conn, QW, "company", "blocked robotics", "asked not to be contacted")
    conn.commit()
    cfg = load_client(QW)
    r = funnel.report(cfg, conn)
    assert r["steps"]["qualified companies (Tier 1-2)"] == 2 and r["steps"]["usable (verified, passed the gate)"] == 1
    assert r["total"] == 2.0 and r["cost_per"]["usable (verified, passed the gate)"] == 2.0      # the client's spend is not counted
    names = [a["name"] for a in l3_contacts.plan(cfg, conn).accounts]
    assert "Blocked Robotics" not in names and "quailworks Co" in names
