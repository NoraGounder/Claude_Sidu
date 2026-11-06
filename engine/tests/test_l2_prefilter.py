"""Layer 2 tests with synthetic HTML (no network)."""

import json
import shutil

import pytest

from gtm import db
from gtm.config import REPO_ROOT, load_client
from gtm.crawl import Page, crawl_site, find_careers_link, parse_html
from gtm.layers import l2_prefilter
from gtm.signals import extract

CLIENT = "the-marble-jar"

HOME = """<html lang="nl"><head><title>Voorbeeld Logistiek</title></head><body>
<p>Wij zijn een familiebedrijf in transport en warehousing. Onze klanten rekenen op ons voor
snelle levering van de goederen naar heel Nederland en een goede service bij elke order.</p>
<a href="/over-ons">Over ons</a> <a href="/werken-bij">Werken bij</a> <a href="https://www.linkedin.com/x">LinkedIn</a>
<p>Wij werken met Exact Online en we groeien snel.</p></body></html>"""

CAREERS = """<html lang="nl"><body><h1>Vacatures</h1>
<a href="/werken-bij/vacature/administratief-medewerker-crediteuren">Administratief medewerker crediteuren (32-40 uur)</a>
<a href="/werken-bij/vacature/orderverwerking-binnendienst">Medewerker orderverwerking binnendienst</a>
<a href="/werken-bij/vacature/chauffeur-ce">Chauffeur CE</a></body></html>"""

JOB = """<html lang="nl"><body><h1>Administratief medewerker crediteuren</h1>
<p>Je verwerkt dagelijks inkomende facturen en voert ze handmatig in. Je werkt veel in Excel.</p></body></html>"""

PLAIN_HOME = """<html lang="en"><body><p>We build machines. Part of the Groot Machine Group.</p>
<a href="/careers">Careers</a></body></html>"""
PLAIN_CAREERS = """<html><body><a href="/careers/jobs/service-engineer">Service Engineer</a>
<a href="/careers/jobs/welder">Welder</a></body></html>"""


class FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested = []

    def get(self, url: str) -> Page:
        self.requested.append(url)
        html = self.pages.get(url)
        if html is None:
            return Page(url=url, status=404)
        return parse_html(url, html)


SITE_A = {
    "https://voorbeeld-logistiek.example": HOME,
    "https://voorbeeld-logistiek.example/werken-bij": CAREERS,
    "https://voorbeeld-logistiek.example/werken-bij/vacature/administratief-medewerker-crediteuren": JOB,
}
SITE_B = {
    "https://groot-machine.example": PLAIN_HOME,
    "https://groot-machine.example/careers": PLAIN_CAREERS,
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_careers_link_and_job_pages_are_found():
    home = parse_html("https://voorbeeld-logistiek.example", HOME)
    assert find_careers_link(home) == "https://voorbeeld-logistiek.example/werken-bij"
    site = crawl_site(FakeFetcher(SITE_A), "voorbeeld-logistiek.example")
    assert site.careers and site.careers.ok
    assert site.job_link_count == 3
    assert "Chauffeur CE" in site.job_titles


def test_evidence_has_source_and_quote():
    site = crawl_site(FakeFetcher(SITE_A), "https://voorbeeld-logistiek.example")
    ev = extract(site)
    labels = {(e.signal, e.label) for e in ev}
    assert ("admin_job_ad", "administratief medewerker") in labels
    assert ("admin_job_ad", "orderverwerking") in labels
    assert ("manual_process_language", "handmatig") in labels
    assert ("manual_process_language", "Excel") in labels
    assert ("erp_mention", "Exact") in labels
    assert ("headcount_growth", "uitbreiding") in labels
    for e in ev:
        assert e.url.startswith("https://voorbeeld-logistiek.example") and e.quote


def test_admin_words_on_homepage_do_not_count_as_job_ads():
    site = crawl_site(FakeFetcher({"https://x.example": "<html><body>Wij verzorgen uw "
                                   "financiële administratie en orderverwerking.</body></html>"}),
                      "https://x.example")
    assert not [e for e in extract(site) if e.signal == "admin_job_ad"]


def test_sap_is_case_sensitive():
    site = crawl_site(FakeFetcher({"https://sap.example": "<html><body>Vers geperst sap en SAP Business One"
                                   " koppelingen.</body></html>"}), "https://sap.example")
    assert [e.quote for e in extract(site) if e.label == "SAP"]
    site2 = crawl_site(FakeFetcher({"https://juice.example": "<html><body>Vers geperst sap.</body></html>"}),
                       "https://juice.example")
    assert not [e for e in extract(site2) if e.label == "SAP"]


def _account(conn, name, website, segments, rng="51-200", country="NL"):
    conn.execute(
        "INSERT INTO accounts(client, name, website, domain, country, employee_range, segments, source, status,"
        " first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (CLIENT, name, website, website.split("//")[-1] if website else None, country, rng,
         json.dumps(segments), "test", "qualified_l1", "t", "t"))


def test_scoring_and_tiers_end_to_end(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _account(conn, "Voorbeeld Logistiek", "https://voorbeeld-logistiek.example", ["logistics_nl"])
    _account(conn, "Groot Machine NL", "https://groot-machine.example", ["manufacturing_nl"])
    _account(conn, "Zonder Site", None, ["installation_nl"])
    _account(conn, "Kleine Groothandel", "https://dicht.example", ["wholesale_nl"], rng="11-50", country=None)
    conn.commit()

    pages = {**SITE_A, **SITE_B}
    summary = l2_prefilter.run(cfg, conn, workers=2, fetcher_factory=lambda: FakeFetcher(pages))
    assert summary["accounts"] == 4

    rows = {r["name"]: dict(r) for r in conn.execute(
        "SELECT a.name, a.status, s.fit, s.signal, s.flags, s.breakdown FROM accounts a"
        " JOIN l2_scores s ON s.account_id=a.id")}

    a = rows["Voorbeeld Logistiek"]
    # fit: in range 30 + sweet spot 10 + logistics 25 + NL 15 + site 5 + Dutch 5 = 90
    assert a["fit"] == 90
    # signals: admin 30 + multiple admin 15 + manual 20 + ERP 10 + growth 10 = 85
    assert a["signal"] == 85 and a["status"] == "tier_1"

    b = rows["Groot Machine NL"]
    assert "subsidiary" in json.loads(b["flags"]) and "review_job_titles" in json.loads(b["flags"])
    assert b["status"] == "tier_3"            # fit only, no signals: cheapest handling

    c = rows["Zonder Site"]
    assert "no_website" in json.loads(c["flags"]) and c["status"] == "tier_3"

    d = rows["Kleine Groothandel"]
    assert d["status"] == "rejected_l2"       # too small, unknown country, site unreachable

    ev = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    assert ev >= 7

    # AI review: Groot Machine's "Service Engineer" is not admin work, but say the reviewer finds
    # an admin title; titles not in the export are ignored, and non-buyers are dropped.
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM accounts")}
    queue = l2_prefilter.review_items(conn, CLIENT)
    assert [q["name"] for q in queue] == ["Groot Machine NL"]
    assert queue[0]["job_titles"] == ["Service Engineer", "Welder"]
    counts = l2_prefilter.apply_review(cfg, conn, [
        {"account_id": ids["Groot Machine NL"], "admin_roles": ["Welder", "Made Up Title"]},
        {"account_id": ids["Zonder Site"], "not_a_buyer": True, "reason": "trade association"},
    ], reviewer="claude")
    assert counts == {"reviewed": 2, "changed_tier": 1, "dropped": 1, "ignored_titles": 1}
    b2 = conn.execute("SELECT signal, tier, flags FROM l2_scores WHERE account_id=?",
                      (ids["Groot Machine NL"],)).fetchone()
    # fit 65 (subsidiary penalty) and a confirmed admin role (30) -> Tier 2
    assert (b2["signal"], b2["tier"]) == (30, "tier_2") and "reviewed:claude" in b2["flags"]
    assert conn.execute("SELECT status FROM accounts WHERE id=?", (ids["Zonder Site"],)).fetchone()[0] == "rejected_l2"


def test_generic_and_non_job_links_are_not_titles():
    careers = """<html><body>
    <a href="/vacatures/123-planner">Bekijk vacature</a>
    <a href="/vacatures/124-administratief">Administratief medewerker</a>
    <a href="/vacatures/124-administratief/">Administratief medewerker</a>
    <a href="/vacatures/cookie-instellingen">Cookie instellingen</a>
    <a href="https://www.linkedin.com/company/x/jobs/">LinkedIn page</a></body></html>"""
    job = "<html><body><h1>Planner binnendienst</h1><p>Plannen van ritten.</p></body></html>"
    pages = {"https://y.example": '<html><body><a href="/vacatures">Vacatures</a></body></html>',
             "https://y.example/vacatures": careers,
             "https://y.example/vacatures/123-planner": job}
    site = crawl_site(FakeFetcher(pages), "http://y.example")
    assert site.job_link_count == 2
    assert site.job_titles == ["Administratief medewerker", "Planner binnendienst"]


def test_excluded_names_are_dropped_before_crawling(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _account(conn, "Branchevereniging Transport", "https://bv.example", ["logistics_nl"])
    conn.commit()
    fetcher = FakeFetcher({})
    summary = l2_prefilter.run(cfg, conn, fetcher_factory=lambda: fetcher)
    assert summary["accounts"] == 0 and fetcher.requested == []
    row = conn.execute("SELECT status, status_reason FROM accounts").fetchone()
    assert tuple(row) == ("rejected_l1", "excluded_keyword:vereniging")
