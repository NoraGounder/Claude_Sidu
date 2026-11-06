import shutil
from pathlib import Path

import pytest

from gtm import budget, db
from gtm.cli import main
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l1_discover
from gtm.normalize import employee_count, normalize_domain, normalize_linkedin_company_url

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


def test_normalisers():
    assert normalize_domain("https://WWW.Voorbeeld.example/contact") == "voorbeeld.example"
    assert normalize_domain("voorbeeld.example") == "voorbeeld.example"
    assert normalize_domain("https://www.linkedin.com/company/x") is None
    assert normalize_domain(None) is None
    assert normalize_linkedin_company_url("https://nl.linkedin.com/company/Acme-BV/about/") == \
        "https://www.linkedin.com/company/acme-bv/"
    assert employee_count("51-200 employees") == (125, "51-200 employees")
    assert employee_count({"start": 201, "end": 500}) == (350, "201-500")
    assert employee_count(180) == (180, None)


def test_plan_builds_one_search_per_enabled_segment(env):
    cfg = load_client(CLIENT)
    plans = l1_discover.plan(cfg, None, None)
    names = [p.segment.name for p in plans]
    assert names == ["logistics_nl", "wholesale_nl", "installation_nl", "manufacturing_nl"]
    first = plans[0].actor_input
    assert first["locations"] == ["Netherlands"]
    assert first["industryIds"] == ["116", "87", "92", "93"]
    assert first["maxItems"] == 1000 and first["takePages"] == 20
    assert round(sum(p.est_cost for p in plans), 2) == 4.0


def test_fixture_run_filters_dedupes_and_suppresses(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    plans = l1_discover.plan(cfg, ["logistics_nl"], 50)
    [res] = l1_discover.run(cfg, conn, plans, fixture=str(FIXTURE))

    assert res.fetched == 8
    assert res.duplicates == 1
    assert res.new == 7
    assert res.qualified == 3   # Voorbeeld Logistiek, Vlaamse Groothandel (BE), Zonder Site
    assert res.rejected == {"excluded_keyword": 1, "size_out_of_range": 1,
                            "suppressed_domain": 1, "country": 1}

    status = {r["name"]: (r["status"], r["status_reason"])
              for r in conn.execute("SELECT name, status, status_reason FROM accounts")}
    assert status["Voorbeeld Logistiek BV"] == ("qualified_l1", None)
    assert status["Bestaande Klant BV"] == ("rejected_l1", "suppressed_domain")
    assert status["Deutsche Lager GmbH"] == ("rejected_l1", "country:DE")
    assert status["Zonder Site Installatie"][0] == "qualified_l1"

    # A second run of the same data adds nothing new.
    [again] = l1_discover.run(cfg, conn, plans, fixture=str(FIXTURE))
    assert again.new == 0 and again.duplicates == 8


def test_budget_guard_blocks_overspend(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    run_id = db.start_run(conn, CLIENT, "L1", "apify", "earlier run", 14.0, {})
    db.finish_run(conn, run_id, "succeeded", 14000, 14.0)
    with pytest.raises(budget.BudgetExceeded):
        budget.check(conn, cfg, "apify", 4.0)
    assert budget.check(conn, cfg, "apify", 0.5)["remaining"] == 1.0


def test_cli_dry_run_spends_nothing(env, capsys):
    assert main(["--client", CLIENT, "discover", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "estimated $4.00" in out and "Dry run" in out
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
