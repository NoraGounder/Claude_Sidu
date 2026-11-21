"""ETA search (clients/eta): iXBRL parsing, Companies House client, discovery, enrichment, sieve 1, ledger.

Synthetic data only: every company number, name, person and figure below is made up.
"""

from datetime import date
from pathlib import Path

import pytest
import requests

from gtm import ixbrl
from gtm.config import load_client
from gtm.eta import discover, enrich, screen, store
from gtm.sources import companies_house as chmod

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2025, 10, 1)
ACCOUNTS = (FIXTURES / "eta_accounts_sample.xhtml").read_bytes()


# ---------- iXBRL ----------

def test_parse_accounts_maps_concepts_by_period():
    acc = ixbrl.parse(ACCOUNTS)
    assert acc.company_number == "99999901"
    assert acc.latest_period == "2025-03-31"
    cy = acc.periods["2025-03-31"]
    assert cy["turnover"] == 12_400_000
    assert cy["operating_profit"] == 1_860_000
    assert cy["depreciation"] == 140_000
    assert cy["employees"] == 84
    assert cy["net_assets"] == 2_900_000
    assert cy["cash"] == 950_000
    assert cy["creditors_after_one_year"] == 100_000       # Creditors + maturity dimension
    assert cy["creditors_within_one_year"] == 300_000
    assert cy["bank_loans"] == 0                           # zero-dash format
    assert acc.periods["2024-03-31"]["turnover"] == 11_100_000   # scale="3"
    assert acc.periods["2024-03-31"]["retained_earnings"] == 2_450_000
    # A dimensioned Equity fact (share capital column) must not be taken as net assets.
    assert cy["net_assets"] != 100


@pytest.mark.parametrize("text,fmt,scale,sign,expected", [
    ("1,234", "ixt2:numdotdecimal", None, None, 1234.0),
    ("(1,234)", None, None, None, -1234.0),
    ("5,000", None, None, "-", -5000.0),
    ("12", None, "3", None, 12000.0),
    ("-", "ixt2:zerodash", None, None, 0.0),
    ("1.234,50", "ixt4:num-comma-decimal", None, None, 1234.5),
    ("n/a", None, None, None, None),
])
def test_parse_number(text, fmt, scale, sign, expected):
    assert ixbrl.parse_number(text, fmt, scale, sign) == expected


# ---------- Companies House client ----------

class FakeResponse:
    def __init__(self, status, payload=None, content=b""):
        self.status_code, self._payload, self.content = status, payload, content
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers, self.auth = list(responses), [], {}, None

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def test_client_retries_429_and_counts_requests():
    sleeps = []
    session = FakeSession([FakeResponse(429), FakeResponse(200, {"items": [{"company_number": "1"}], "hits": 1})])
    ch = chmod.CompaniesHouseClient(api_key="placeholder", session=session, sleep=sleeps.append)
    data = ch.advanced_search(sic_codes=["71200"], incorporated_to="2015-12-31", size=10)
    assert data["hits"] == 1 and ch.requests_made == 2 and sleeps
    url, params, _ = session.calls[0]
    assert url.endswith("/advanced-search/companies")
    assert params["sic_codes"] == "71200" and params["incorporated_to"] == "2015-12-31"
    assert session.auth == ("placeholder", "")


def test_client_401_explains_the_key_and_stops():
    ch = chmod.CompaniesHouseClient(api_key="x", session=FakeSession([FakeResponse(401, {"error": "Invalid"})]))
    with pytest.raises(chmod.CompaniesHouseError, match="rejected the API key"):
        ch.profile("99999901")


def test_client_paces_under_the_window_and_respects_the_run_cap():
    sleeps, now = [], [0.0]
    session = FakeSession([FakeResponse(200, {"x": i}) for i in range(5)])
    ch = chmod.CompaniesHouseClient(api_key="x", session=session, per_window=2, max_requests=3,
                                    sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)),
                                    clock=lambda: now[0])
    ch.profile("1"); ch.profile("2"); ch.profile("3")
    assert sleeps and sleeps[0] > 200          # third call waited for the 5-minute window
    with pytest.raises(chmod.RequestCapReached):
        ch.profile("4")


def test_empty_search_is_not_an_error():
    ch = chmod.CompaniesHouseClient(api_key="x", session=FakeSession([FakeResponse(404, {})]))
    assert ch.advanced_search(sic_codes=["1"]) == {"items": [], "hits": 0}


def test_document_links_use_the_document_api_host():
    assert chmod._doc_url("https://frontend-doc-api.company-information.service.gov.uk/document/abc") == \
        "https://document-api.company-information.service.gov.uk/document/abc"


def test_client_needs_a_key(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    with pytest.raises(chmod.CompaniesHouseError, match="COMPANIES_HOUSE_API_KEY"):
        chmod.CompaniesHouseClient()


# ---------- pipeline with a fake register ----------

def _company(number, name, created="1998-05-01", sic="71200"):
    return {"company_number": number, "company_name": name, "company_status": "active", "company_type": "ltd",
            "date_of_creation": created, "sic_codes": [sic],
            "registered_office_address": {"locality": "Exampletown", "postal_code": "ZZ1 1ZZ"}}


def _profile(number, created="1998-05-01", acc_type="total-exemption-full", made_up_to="2025-03-31",
             insolvency=False, overdue=False):
    return {"company_number": number, "company_status": "active", "date_of_creation": created,
            "has_insolvency_history": insolvency, "has_charges": False,
            "accounts": {"overdue": overdue, "last_accounts": {"type": acc_type, "made_up_to": made_up_to}}}


class FakeRegister:
    """Stands in for CompaniesHouseClient with the same method names."""

    def __init__(self, companies, profiles, pscs=None, officers=None, docs=None):
        self.companies, self.profiles = companies, profiles
        self._pscs, self._officers, self.docs = pscs or {}, officers or {}, docs or {}
        self.requests_made = 0

    def advanced_search(self, sic_codes=None, size=500, start_index=0, **kw):
        self.requests_made += 1
        items = [c for c in self.companies if c["sic_codes"][0] in sic_codes]
        return {"items": items[start_index:start_index + size], "hits": len(items)}

    def profile(self, number):
        self.requests_made += 1
        return self.profiles.get(number)

    def accounts_filings(self, number, limit=10):
        self.requests_made += 1
        if number not in self.docs:
            return []
        return [{"type": "AA", "date": "2025-09-01", "transaction_id": f"T{number}",
                 "links": {"document_metadata": f"https://frontend-doc-api.company-information.service.gov.uk/document/{number}"}}]

    def document_formats(self, url):
        self.requests_made += 1
        return {"resources": {"application/xhtml+xml": {}, "application/pdf": {}}}

    def document_content(self, url):
        self.requests_made += 1
        return self.docs[url.rsplit("/", 1)[-1]]

    def pscs(self, number):
        self.requests_made += 1
        return self._pscs.get(number, [])

    def officers(self, number):
        self.requests_made += 1
        return self._officers.get(number, [])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path))
    cfg = load_client("eta")
    eta = store.load_eta(cfg)
    conn = store.connect(tmp_path / "engine.db")
    return cfg, eta, conn


def _owner_psc(name, year, band="75-to-100", kind="individual-person-with-significant-control"):
    return {"kind": kind, "name": name, "date_of_birth": {"year": year, "month": 6},
            "natures_of_control": [f"ownership-of-shares-{band}-percent"], "links": {"self": f"/psc/{name}"}}


def _director(name, year):
    return {"name": name, "officer_role": "director", "appointed_on": "1998-05-01",
            "date_of_birth": {"year": year, "month": 3}, "links": {"self": f"/officer/{name}"}}


def _register():
    companies = [
        _company("99999901", "EXAMPLE TESTING SERVICES LIMITED"),
        _company("99999902", "EXAMPLE HOLDINGS LIMITED"),                       # dropped by name
        _company("99999903", "INSOLVENT EXAMPLE LIMITED"),
        _company("99999904", "GROUP-OWNED EXAMPLE LIMITED"),
        _company("99999905", "PAPER FILER EXAMPLE LIMITED", sic="43220"),
    ]
    profiles = {"99999901": _profile("99999901"), "99999903": _profile("99999903", insolvency=True),
                "99999904": _profile("99999904"), "99999905": _profile("99999905")}
    pscs = {"99999901": [_owner_psc("Owner One", 1961)],
            "99999904": [_owner_psc("Parent Group Ltd", None, kind="corporate-entity-person-with-significant-control")],
            "99999905": [_owner_psc("Owner Five", 1980, band="50-to-75")]}
    officers = {"99999901": [_director("Owner One", 1961), _director("Manager Two", 1985)]}
    docs = {"99999901": ACCOUNTS, "99999904": ACCOUNTS.replace(b"99999901", b"99999904")}
    return FakeRegister(companies, profiles, pscs, officers, docs)


def _run_all(env, reg):
    cfg, eta, conn = env
    plans = discover.plan(eta, conn, cfg.slug, ["71200", "43220"])
    discover.run(reg, conn, cfg.slug, eta, plans)
    enrich.profile_step(reg, conn, cfg.slug, eta, today=TODAY)
    enrich.accounts_step(reg, conn, cfg.slug, eta)
    enrich.owners_step(reg, conn, cfg.slug, eta)
    return screen.run(conn, cfg.slug, eta, today=TODAY)


def test_pipeline_end_to_end(env):
    cfg, eta, conn = env
    reg = _register()
    summary = _run_all(env, reg)

    stages = {r["company_number"]: (r["stage"], r["stage_reason"])
              for r in conn.execute("SELECT * FROM eta_companies WHERE client='eta'")}
    assert stages["99999902"] == ("dropped", "name_holdings")
    assert stages["99999903"] == ("dropped", "insolvency_history")
    assert stages["99999901"][0] == "screened"

    by_number = {r["company_number"]: r for r in screen.ranked(conn, cfg.slug, ("pass", "review", "fail"))}
    good = by_number["99999901"]
    assert good["verdict"] == "pass" and good["score"] >= 80
    m = good["metrics"]
    assert m["turnover"] == 12_400_000 and m["ebitda"] == 2_000_000
    assert m["ebitda_margin"] == 0.1613 and m["rotc"] > 0.2
    assert m["owner_age"] == 64 and m["owner_band"] == "75-100"
    assert m["directors"] == 2 and m["directors_under_55"] == 1

    assert by_number["99999904"]["verdict"] == "fail"
    assert "no_motivated_owner_group_owned" in by_number["99999904"]["hard_fails"]

    # No online accounts: kept, but scored on what is known and never passed on unknowns alone.
    paper = by_number["99999905"]
    assert paper["verdict"] in ("review", "fail") and paper["metrics"]["turnover"] is None
    assert summary["pass"] == 1


def test_evidence_ledger_marks_unknowns_with_next_steps(env):
    cfg, eta, conn = env
    _run_all(env, _register())
    ledger = {r["claim"]: r for r in store.evidence(conn, cfg.slug, "99999901")}
    assert ledger["Turnover"]["status"] == "public" and ledger["Turnover"]["value"] == "£12,400,000"
    assert ledger["Turnover"]["source"].endswith("/99999901/filing-history")
    assert ledger["Owner earnings"]["status"] == "unknown" and "sieve 3" in ledger["Owner earnings"]["next_step"]
    assert ledger["Customer concentration"]["status"] == "unknown"

    paper = {r["claim"]: r for r in store.evidence(conn, cfg.slug, "99999905")}
    assert paper["Turnover"]["status"] == "unknown"
    assert "profit and loss" in paper["Turnover"]["next_step"]


def test_ledger_never_downgrades_a_confirmed_claim(env):
    cfg, _, conn = env
    store.record_evidence(conn, "eta", "1", "Turnover", "£3,000,000", "seller_reported", "owner email")
    store.record_evidence(conn, "eta", "1", "Turnover", None, "unknown", None, "ask")
    assert store.evidence(conn, "eta", "1")[0]["status"] == "seller_reported"


def test_discovery_continues_where_it_stopped(env):
    cfg, eta, conn = env
    reg = FakeRegister([_company(f"9999{i:04d}", f"FIRM {i} LIMITED") for i in range(5)], {})
    eta = {**eta, "search": {**eta["search"], "page_size": 2}}
    first = discover.run(reg, conn, cfg.slug, eta, discover.plan(eta, conn, cfg.slug, ["71200"], max_per_code=3))
    assert first[0].fetched == 3 and not first[0].exhausted
    second = discover.run(reg, conn, cfg.slug, eta, discover.plan(eta, conn, cfg.slug, ["71200"], max_per_code=3))
    assert second[0].fetched == 2 and second[0].new == 2 and second[0].exhausted
    assert discover.plan(eta, conn, cfg.slug, ["71200"]) == []      # exhausted codes are skipped


def test_rerun_is_idempotent_and_reads_documents_from_cache(env):
    cfg, eta, conn = env
    reg = _register()
    _run_all(env, reg)
    before = reg.requests_made
    assert screen.run(conn, cfg.slug, eta, rescreen=True, today=TODAY)["pass"] == 1
    assert reg.requests_made == before


def test_document_naming_another_company_is_ignored(env):
    cfg, eta, conn = env
    reg = _register()
    reg.docs["99999901"] = ACCOUNTS.replace(b">99999901<", b">12345678<")
    _run_all(env, reg)
    row = conn.execute("SELECT stage_reason FROM eta_companies WHERE company_number='99999901'").fetchone()
    assert row["stage_reason"] == "no_online_accounts"


def test_ownership_band_takes_the_highest_share_band():
    assert enrich.ownership_band(["voting-rights-75-to-100-percent", "ownership-of-shares-25-to-50-percent",
                                  "ownership-of-shares-50-to-75-percent"]) == "50-75"
    assert enrich.ownership_band(["right-to-appoint-and-remove-directors"]) is None


def test_cli_dry_run_calls_nothing(tmp_path, monkeypatch, capsys):
    from gtm.cli import main

    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: pytest.fail("no network in a dry run"))
    assert main(["--client", "eta", "eta-discover", "--dry-run", "--code", "71200"]) == 0
    out = capsys.readouterr().out
    assert "71200" in out and "Dry run" in out


# ---------- sieve 2: Stanford industry scorecard + 7 Powers ----------

from gtm.crawl import Page
from gtm.eta import qualify
from gtm.sources.jev import JevResult


class FakeJev:
    """Answers like TypeSafe Jev 1.14: score questions get 0..2 (criteria index scale)."""

    def __init__(self, industry=2.0, powers=None):
        self.industry, self.powers, self.calls = industry, powers or {}, []

    def decide(self, state, questions, timeout=60):
        self.calls.append((state, questions))
        if "website_text" in state:
            answers = {k: {"type": "score", "score": self.powers.get(k, 0.2)} for k in questions}
        else:
            answers = {k: {"type": "score", "score": self.industry} for k in questions}
        return JevResult(answers, "typesafe/jev-1.14-20261014", 100, 20, 0.0001, 50, "req")


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        return self.pages.get(url) or Page(url=url, status=404)


def _site(number):
    home = Page(url="https://www.exampletestingservices.co.uk/", status=200, title="Example Testing Services",
                text="UKAS accredited calibration and testing for aerospace customers since 1998.",
                links=[("https://www.exampletestingservices.co.uk/privacy", "Privacy")])
    legal = Page(url="https://www.exampletestingservices.co.uk/privacy", status=200,
                 text=f"Example Testing Services Limited, registered in England no. {number}.")
    return {home.url: home, legal.url: legal}


@pytest.fixture
def screened(env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    _run_all(env, _register())
    return env


def test_domain_candidates_and_number_match():
    c = qualify.domain_candidates("EXAMPLE TESTING SERVICES LIMITED")
    assert c[0] == "exampletestingservices.co.uk" and "example-testing-services.com" in c
    assert qualify.shows_number("Registered no. 9999901 in England", "09999901")
    assert not qualify.shows_number("Call 0199999901", "99999901")


def test_industry_scorecard_is_one_decision_per_code_and_cached(screened):
    cfg, eta, conn = screened
    jev = FakeJev(industry=1.6)
    first = qualify.score_industries(conn, cfg, eta, {"71200": "Technical testing"}, jev)
    assert first == {"71200": 26.0}                      # 10 criteria x (1 + 1.6)
    qualify.score_industries(conn, cfg, eta, {"71200": "Technical testing"}, jev)
    assert len(jev.calls) == 1
    state, questions = jev.calls[0]
    assert set(questions) == set(eta["industry_scorecard"]["criteria"]) and state["industry_code"] == "UK SIC 2007 71200"


def test_qualify_finds_verified_site_and_counts_clear_powers(screened):
    cfg, eta, conn = screened
    jev = FakeJev(industry=1.6, powers={"cornered_resource": 1.8, "switching_costs": 1.6, "branding": 0.9})
    out = qualify.run(conn, cfg, eta, fetcher=FakeFetcher(_site("99999901")), jev=jev)
    assert out["websites_found"] == 1 and out["qualified"] == 1
    top = qualify.qualified(conn, cfg.slug)[0]
    assert top["company_number"] == "99999901" and top["verdict"] == "qualified"
    assert sorted(top["breakdown"]["clear_powers"]) == ["cornered_resource", "switching_costs"]
    ledger = {r["claim"]: r for r in store.evidence(conn, cfg.slug, "99999901")}
    assert ledger["7 Powers: cornered resource"]["status"] == "unverified"
    assert ledger["Stanford industry score"]["value"] == "26 of 30"
    powers_q = [q for s, q in jev.calls if "website_text" in s][0]
    assert set(powers_q) == set(eta["seven_powers"]["powers"])


def test_no_verified_site_means_watch_not_qualified(screened):
    cfg, eta, conn = screened
    out = qualify.run(conn, cfg, eta, fetcher=FakeFetcher(_site("12345678")), jev=FakeJev(industry=1.6))
    assert out["websites_found"] == 0 and out["qualified"] == 0
    row = conn.execute("SELECT verdict FROM eta_screen WHERE company_number='99999901' AND sieve=2").fetchone()
    assert row["verdict"] == "watch"


def test_weak_industry_is_not_qualified(screened):
    cfg, eta, conn = screened
    out = qualify.run(conn, cfg, eta, fetcher=FakeFetcher(_site("99999901")),
                      jev=FakeJev(industry=0.3, powers={"process_power": 2.0}))
    assert out["not_qualified"] >= 1 and out["qualified"] == 0


def test_qualify_refuses_a_non_jev_model(screened):
    from gtm.sources.jev import JevPolicyError

    cfg, eta, conn = screened
    cfg.ai["model"] = "openrouter/auto"
    with pytest.raises(JevPolicyError):
        qualify.run(conn, cfg, eta, fetcher=FakeFetcher({}), jev=FakeJev())


def test_cloud_placeholder_leaves_the_header_to_the_proxy():
    session = FakeSession([])
    chmod.CompaniesHouseClient(api_key="proxy-injected", session=session)
    assert session.auth is None


FRS102_EQUITY = b"""<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi"><body><ix:header><ix:resources>
<xbrli:context id="re"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="core:EquityClassesDimension">core:RetainedEarningsAccumulatedLosses</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-03-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="nc"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="core:FinancialInstrumentCurrentNon-currentDimension">core:Non-currentFinancialInstruments</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-03-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="d"><xbrli:entity></xbrli:entity><xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period></xbrli:context>
</ix:resources></ix:header>
<ix:nonFraction name="core:Equity" contextRef="re" unitRef="GBP">412,000</ix:nonFraction>
<ix:nonFraction name="core:Creditors" contextRef="nc" unitRef="GBP">55,000</ix:nonFraction>
<ix:nonFraction name="core:IncreaseFromDepreciationChargeForYearPropertyPlantEquipment" contextRef="d" unitRef="GBP">21,000</ix:nonFraction>
</body></html>"""


def test_real_frs102_tagging_of_reserves_creditors_and_depreciation():
    p = ixbrl.parse(FRS102_EQUITY).periods["2025-03-31"]
    assert p["retained_earnings"] == 412_000
    assert p["creditors_after_one_year"] == 55_000
    assert p["depreciation"] == 21_000
