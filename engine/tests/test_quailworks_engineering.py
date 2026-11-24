"""Quailworks Engineering (clients/quailworks-engineering): the engineering-design offer on the same engine.
Config checks only, with synthetic text; nothing is fetched, written to a vendor or sent."""

import re

import yaml

from gtm.config import REPO_ROOT, load_client
from gtm.layers import l1_hiring, l5_copy, l6_send
from gtm.signals import rules_for
from gtm.sources.jev import check_policy

QWE = "quailworks-engineering"


def _labels(cfg, signal: str, text: str) -> list[str]:
    return [label for label, pattern in rules_for(cfg.scoring).rules[signal] if re.search(pattern, text, re.I)]


def test_config_loads_with_every_launch_safeguard():
    cfg = load_client(QWE)
    check_policy(cfg.ai)                                           # Jev 1.14 only, no fallback
    sending = l6_send.load_sending(cfg)
    gate = yaml.safe_load((cfg.root / "gate.yaml").read_text(encoding="utf-8"))
    assert cfg.client["sender"]["consent_to_send_in_name"] == "granted"     # given 2026-11-24 (decisions.md E2)
    assert sending["campaign_prefix"] == "QWE" and sending["send_order"] == "best_first"
    assert sending["min_warmup_days"] >= 14 and sending["min_warmup_reputation"] >= 95 and sending["require_backup"]
    assert set(gate["verify_statuses"]) >= {"DELIVERABLE", "HIGH_PROBABILITY"}
    assert gate["contact_countries"] == ["GB", "US"] and set(cfg.icp.allowed_countries) == {"GB", "US"}
    assert "Quailworks sp. z o.o." in gate["gdpr_notice"]["en"] and "'stop'" in gate["gdpr_notice"]["en"]
    assert cfg.client["crm"]["hubspot_token_env"] == "HUBSPOT_TOKEN_QUAILWORKS"   # one CRM for one company (E1)
    assert cfg.limits.month_budget_usd["fullenrich"] <= 20 and cfg.limits.month_budget_usd["blitzapi"] == 0


def test_never_shares_a_sending_domain_and_holds_companies_the_gtm_offer_emailed():
    cfg = load_client(QWE)
    sending = l6_send.load_sending(cfg)
    assert l6_send.shared_domains(cfg) == []                         # one domain, one client
    assert sending["mailbox_domains"] == ["quailworks.work", "quailworks.dev"]   # lent by Quailworks GTM (E2)
    assert sending["avoid_overlap_with"] == ["quailworks"] and sending["overlap_days"] >= 90   # E12


def test_hiring_searches_cover_the_uk_and_us_design_market():
    cfg = load_client(QWE)
    plans = l1_hiring.plan(cfg)
    assert len(plans) == 7 and all(p.est_cost == 0 for p in plans)  # flat plan: no charge per record
    assert {c for p in plans for c in p.company["hq"]["country_code"]["include"]} == {"GB", "US"}
    assert "Mechanical Design Engineer" in plans[0].job["title"]["include"]
    assert all(p.company["employee_count"] == {"min": 11, "max": 500} for p in plans)


def test_design_roles_count_once_and_electronics_roles_do_not_count():
    cfg = load_client(QWE)
    assert _labels(cfg, "design_job_ad", "Senior Mechanical Design Engineer") == ["mechanical design engineer"]
    assert _labels(cfg, "design_job_ad", "Chassis Design Engineer") == ["chassis engineer"]
    assert _labels(cfg, "design_job_ad", "Composites Design Engineer") == ["composites design engineer"]
    assert _labels(cfg, "design_job_ad", "Design Engineer - Structures") == ["design engineer"]
    assert _labels(cfg, "design_job_ad", "Electronics Design Engineer") == []
    assert _labels(cfg, "design_job_ad", "PCB Design Engineer") == []
    assert _labels(cfg, "cad_platform", "Experience with CATIA V5 or 3DEXPERIENCE required") == ["CATIA"]
    assert _labels(cfg, "cad_platform", "Siemens NX and Teamcenter") == ["Siemens NX"]


def test_email_one_is_short_names_no_employer_and_passes_the_banned_phrase_check():
    cfg = load_client(QWE)
    seq = l5_copy.load_sequence(cfg)
    gate = yaml.safe_load((cfg.root / "gate.yaml").read_text(encoding="utf-8"))
    facts = {"job_title": {"value": "mechanical design engineer"}}
    subject, steps = l5_copy.render(seq, "en", "design_job_ad", "design", facts, {"id": 7, "first_name": "Alex"},
                                    {"name": "Northfield Motorsport Ltd"}, {"first_name": "Sam"}, gate["gdpr_notice"]["en"])
    body = steps[0]["body"]
    assert subject == "your mechanical design engineer opening"
    assert body.startswith(("Hi Alex,", "Hello Alex,")) and "opening at Northfield Motorsport." in body
    assert "one-page profile" in body and body.endswith(gate["gdpr_notice"]["en"])
    words = body.replace(gate["gdpr_notice"]["en"], "").split()
    assert len(words) <= 110
    text = " ".join(s["body"] for s in steps).lower() + " " + subject.lower()
    banned = l5_copy.BANNED + tuple(p.lower() for p in seq["banned_phrases"])
    assert not any(b in text for b in banned) and "{" not in text
    for hook in seq["hook_priority"]:                            # every hook renders with its own fact
        need = l5_copy.hook_meta(seq, hook)["needs"]
        f = {need: {"value": {"cad": "CATIA", "trade_show": "Autosport International", "open_roles": 9}.get(need, "design engineer")}} if need else {}
        _, s = l5_copy.render(seq, "en", hook, "design", f, {"id": 1, "first_name": "Alex"}, {"name": "Acme Ltd"},
                              {"first_name": "Sam"}, "Notice.")
        assert "{" not in s[0]["body"] and "Acme" in s[0]["body"]


# ---------- BlitzAPI first (decisions.md E14) ----------

class StubBlitz:
    records_remaining = 1000

    def __init__(self, companies=None, people=None):
        self.companies, self.people_by_url, self.calls = companies or [], people or {}, []

    def search_companies(self, company, max_results, cursor=None):
        self.calls.append(("companies", company, max_results))
        return {"results": self.companies[:max_results], "cursor": None}

    def people(self, company_linkedin_url, cascade, max_results=4):
        self.calls.append(("people", company_linkedin_url, cascade, max_results))
        return self.people_by_url.get(company_linkedin_url, [])[:max_results]


def test_company_searches_replace_apify_and_store_accounts(tmp_path, monkeypatch):
    import shutil
    from gtm import db
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / QWE, clients / QWE, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    cfg = load_client(QWE)
    assert not [s for s in cfg.icp.segments if s.enabled] and cfg.limits.month_budget_usd["apify"] == 0
    plans = l1_hiring.plan_companies(cfg)
    assert len(plans) == 6 and {p.kind for p in plans} == {"companies"} and all(p.job == {} for p in plans)
    assert plans[0].company["keywords"] == {"include": ["motorsport", "racing", "race car"]}
    stub = StubBlitz(companies=[{"name": "Northfield Motorsport Ltd", "domain": "northfield.example",
                                 "website": "https://northfield.example", "linkedin_url": "https://www.linkedin.com/company/northfield",
                                 "industry": "Motor Vehicle Manufacturing", "size": "51-200", "employees_on_linkedin": 80,
                                 "hq": {"country_code": "GB", "city": "Banbury"}}])
    conn = db.connect()
    res = l1_hiring.run(cfg, conn, plans[:1], client=stub)
    assert res[0].new == 1 and res[0].qualified == 1 and stub.calls[0][0] == "companies"
    row = conn.execute("SELECT source, status, country FROM accounts WHERE client=?", (QWE,)).fetchone()
    assert tuple(row) == ("blitzapi:company-search:companies_motorsport_uk", "qualified_l1", "GB")
    assert l1_hiring.records_used(conn, QWE) == 1                  # counts towards limits.yaml blitzapi_records


def test_people_search_on_blitzapi_first_with_fullenrich_only_as_fallback(tmp_path, monkeypatch):
    import json as _json
    import shutil
    from test_l3_contacts import CLIENT as TMJ, StubFE, StubJev, _account
    from gtm import db
    from gtm.layers import l3_contacts
    from gtm.sources.fullenrich import FullEnrichClient
    from gtm.sources.jev import JevClient
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / TMJ, clients / TMJ, ignore=shutil.ignore_patterns("private"))
    path = clients / TMJ / "scoring.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.setdefault("enrichment_policy", {})["people_first"] = "blitzapi"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for k, v in {"GTM_CLIENTS_DIR": str(clients), "GTM_DATA_DIR": str(tmp_path / "data"),
                 "OPENROUTER_API_KEY": "proxy-injected", "FULLENRICH_API_KEY": "proxy-injected"}.items():
        monkeypatch.setenv(k, v)
    cfg = load_client(TMJ)
    conn = db.connect()
    a = _account(conn, "Groothandel BV", "groothandel.example", "tier_2", "51-200")
    _account(conn, "Groot BV", "groot.example", "tier_2", "201-500")          # no LinkedIn page: FullEnrich
    url = "https://www.linkedin.com/company/groothandel-bv"
    conn.execute("UPDATE accounts SET linkedin_url=? WHERE id=?", (url, a))
    conn.commit()

    def person(first, title, here=True):
        return {"icp": 1, "ranking": 1, "person": {
            "first_name": first, "last_name": "Tester", "full_name": f"{first} Tester", "headline": "Headline only",
            "linkedin_url": f"https://www.linkedin.com/in/{first.lower()}", "location": {"country_code": "NL"},
            "experiences": [{"job_title": title, "job_is_current": True,
                             "company_linkedin_url": url + "/" if here else "https://www.linkedin.com/company/other"}]}}
    blitz = StubBlitz(people={url: [person("Anna", "Operations Manager"), person("Bram", "Financieel Directeur")]})
    fe_session = StubFE()
    t = l3_contacts.find_people(cfg, conn, l3_contacts.plan(cfg, conn), fe=FullEnrichClient(session=fe_session),
                                jev=JevClient(cfg.ai, session=StubJev()), blitz=blitz)
    assert t["blitzapi_people"] == 2 and t["fullenrich_searches"] == 1
    searched = [j["current_company_domains"][0]["value"] for u, j in fe_session.posts if u.endswith("/people/search")]
    assert searched == ["groot.example"]                           # FullEnrich only where BlitzAPI had nobody
    cascade = blitz.calls[0][2]
    assert cascade[0]["include_title"] == cfg.icp.personas[next(iter(cfg.icp.personas))][:50]
    rows = {r["first_name"]: (r["title"], r["data_source"]) for r in conn.execute(
        "SELECT first_name, title, data_source FROM contacts WHERE account_id=?", (a,))}
    assert rows["Anna"][0] == "Operations Manager" and rows["Anna"][1].startswith("BlitzAPI people search")
    used = conn.execute("SELECT items, actual_cost FROM runs WHERE client=? AND vendor='blitzapi'", (TMJ,)).fetchone()
    assert tuple(used) == (2, 0.0)                                 # flat plan: records logged, nothing charged
    _json.dumps(t)
