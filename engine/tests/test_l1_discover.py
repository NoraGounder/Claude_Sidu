import json
import shutil
from pathlib import Path

import pytest

from gtm import budget, db
from gtm.cli import main
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l1_discover
from gtm.normalize import member_count, normalize_domain, normalize_linkedin_company_url, size_range
from gtm.sources.apify import RunResult

FIXTURE = Path(__file__).parent / "fixtures" / "company_search_sample.json"
CLIENT = "the-marble-jar"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Copy the real client config into a temp folder and add a private exclusion list."""
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT,
                    ignore=shutil.ignore_patterns("private"))
    private = clients / CLIENT / "private"
    private.mkdir()
    (private / "exclusions.csv").write_text(
        "kind,value,reason\ndomain,https://www.bestaande-klant.example,current client\n", encoding="utf-8")
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


class StubApify:
    """Stands in for ApifyClient: returns fixture items and records the input it was given."""

    def __init__(self):
        self.inputs = []

    def run_actor(self, actor, actor_input):
        self.inputs.append(actor_input)
        items = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"][:2]
        return RunResult(items=items, run_id="stub", status="SUCCEEDED", cost_usd=0.001)


def test_normalisers():
    assert normalize_domain("https://WWW.Voorbeeld.example/contact") == "voorbeeld.example"
    assert normalize_domain("voorbeeld.example") == "voorbeeld.example"
    assert normalize_domain("https://www.linkedin.com/company/x") is None
    assert normalize_domain(None) is None
    assert normalize_linkedin_company_url("https://nl.linkedin.com/company/Acme-BV/about/") == \
        "https://www.linkedin.com/company/acme-bv/"
    assert size_range("51-200 employees") == (51, 200)
    assert size_range({"start": 201, "end": 500}) == (201, 500)
    assert member_count(180) == 180 and member_count("180") is None


def test_plan_builds_one_search_per_enabled_segment(env):
    cfg = load_client(CLIENT)
    plans = l1_discover.plan(cfg, None, None, conn=db.connect())
    names = [p.segment.name for p in plans]
    assert names == ["logistics_nl", "wholesale_nl", "installation_nl", "manufacturing_nl"]
    first = plans[0].actor_input
    assert first["scraperMode"] == "full"
    assert first["locations"] == ["Netherlands"]
    assert first["industryIds"] == ["116", "87", "92", "93"]
    assert first["maxItems"] == 300 and first["startPage"] == 1 and first["takePages"] == 6
    # 4 segments x 300 full-mode companies, inside the $5 monthly cap
    assert round(sum(p.est_cost for p in plans), 2) == 4.8


def test_fixture_run_filters_dedupes_and_suppresses(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    plans = l1_discover.plan(cfg, ["logistics_nl"], 50, conn=conn)
    [res] = l1_discover.run(cfg, conn, plans, fixture=str(FIXTURE))

    assert res.fetched == 11
    assert res.duplicates == 1
    assert res.new == 10
    assert res.qualified == 5
    assert res.rejected == {"excluded_keyword": 1, "size_out_of_range": 1,
                            "suppressed_domain": 1, "country": 2}

    rows = {r["name"]: r for r in conn.execute("SELECT * FROM accounts")}
    assert rows["Voorbeeld Logistiek BV"]["status"] == "qualified_l1"
    assert rows["Bestaande Klant BV"]["status_reason"] == "suppressed_domain"
    assert rows["Deutsche Lager GmbH"]["status_reason"] == "country:DE"
    assert rows["Zonder Site Installatie"]["status"] == "qualified_l1"
    # Regression: HQ country, not the first office; stated size band, not LinkedIn member count
    regio = rows["Regio Installatie Groep"]
    assert (regio["status"], regio["country"], regio["city"]) == ("qualified_l1", "NL", "Breda")
    assert regio["employee_count"] == 38 and regio["employee_range"] == "51-200"
    assert rows["Overzee Supply Inc"]["status_reason"] == "country:US"
    assert rows["Korte Modus Transport"]["country"] == "NL"

    # A second run of the same data adds nothing new.
    [again] = l1_discover.run(cfg, conn, plans, fixture=str(FIXTURE))
    assert again.new == 0 and again.duplicates == 11


def test_live_runs_continue_from_next_page_and_price_results(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    stub = StubApify()
    [res] = l1_discover.run(cfg, conn, l1_discover.plan(cfg, ["logistics_nl"], None, conn=conn), client=stub)
    assert stub.inputs[0]["startPage"] == 1 and stub.inputs[0]["takePages"] == 6
    # Reported cost ($0.001) is lower than results x list price, so the ledger keeps the higher one.
    assert res.cost_usd == round(2 * 0.004, 4)
    assert db.month_spend(conn, CLIENT, "apify") == res.cost_usd

    [nxt] = l1_discover.plan(cfg, ["logistics_nl"], None, conn=conn)
    assert nxt.start_page == 7

    db.set_next_page(conn, CLIENT, "logistics_nl", 21)
    assert l1_discover.plan(cfg, ["logistics_nl"], None, conn=conn) == []
    assert "logistics_nl" in l1_discover.exhausted_segments(cfg, conn)


def test_budget_guard_blocks_overspend(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    run_id = db.start_run(conn, CLIENT, "L1", "apify", "earlier run", 4.0, {})
    db.finish_run(conn, run_id, "succeeded", 1000, 4.0)
    with pytest.raises(budget.BudgetExceeded):
        budget.check(conn, cfg, "apify", 4.8)
    assert budget.check(conn, cfg, "apify", 0.5)["remaining"] == 1.0


def test_cli_dry_run_spends_nothing(env, capsys):
    assert main(["--client", CLIENT, "discover", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "estimated $4.80" in out and "Dry run" in out and "pages 1-6" in out
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
