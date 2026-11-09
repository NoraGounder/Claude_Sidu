"""GTM brain context for Jev 1.14 and the outcome report (synthetic data only)."""

import json

import pytest
from test_l6_send import CLIENT, StubJev, StubSmartlead, _approved, make_env

from gtm import best_clients, brain, db, learn
from gtm.config import load_client
from gtm.layers import l2_jev, l2_prefilter, l6_send
from gtm.sources.jev import JevClient
from gtm.sources.smartlead import SmartleadClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def test_context_only_uses_confirmed_and_hypothesis_entries(env):
    cfg = load_client(CLIENT)
    for purpose in ("account", "contact", "angle", "reply"):
        text = json.dumps(brain.jev_context(cfg, purpose))
        assert len(text) <= brain.MAX_CHARS
        assert "only if integrations are confirmed" not in text      # ask_mithun stays out
        assert "Mendix" not in text and "pebls" not in text          # jev: false notes stay out
    assert brain.jev_context(cfg, "angle")["why_now_signals"]["admin_job_ad"]


def test_context_is_empty_without_a_brain(env):
    (env / "brain.yaml").unlink()
    assert brain.jev_context(load_client(CLIENT), "account") == {}


def test_layer2_request_carries_the_brain(env):
    cfg = load_client(CLIENT)
    item = {"name": "Groothandel BV", "industry": "Wholesale", "country": "NL", "employee_range": "51-200",
            "home_title": "Home", "home_excerpt": "We distribute parts", "job_titles": ["Order entry clerk"]}
    state, questions, _ = l2_jev.build_request(cfg, item)
    assert state["seller_context"]["buyer_pains"] and state["seller_context"]["alternatives_and_competitors"]
    assert "seller_context" in questions["not_a_buyer"]["instructions"]


def test_learn_counts_conversations_per_signal(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    acc = _approved(conn, "Groothandel BV", "NL", "Anna", "anna@groothandel.example")
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, breakdown, scored_at)"
                 " VALUES (?,?,?,?,?,?,?,?)", (acc, 80, 50, "tier_1", 1, 0,
                                               json.dumps({"signals": {"admin_job_ad": 30, "erp_mention": 0}}), "t"))
    conn.commit()
    sl_stub = StubSmartlead()
    sl = SmartleadClient(api_key="test-key", session=sl_stub)
    l6_send.push(cfg, conn, sl=sl)
    sl_stub.replies = {"anna@groothandel.example": "Sounds useful, can we talk on Thursday?"}
    l6_send.sync(cfg, conn, sl=sl, jev=JevClient(cfg.ai, session=StubJev()))
    report = learn.outcomes(cfg, conn)
    assert report["signal"]["admin_job_ad"]["conversations"] == 1 and "erp_mention" not in report["signal"]
    assert report["tier"]["tier_1"] == {"contacted": 1, "replied": 1, "conversations": 1, "unsubscribed": 0,
                                        "bounced": 0}
    assert any("admin_job_ad: 1 contacted" in line for line in learn.format_report(report))


# ---------- best clients as lookalikes ----------

class StubFetcher:
    def get(self, url):
        from gtm.crawl import Page
        return Page(url=url, status=200, title="Fresh produce wholesale",
                    text="We import and distribute fruit and vegetables to 400 retailers across the Benelux.")


def _write_best_clients(client_dir):
    (client_dir / "private" / "best_clients.csv").write_text(
        "name,domain,industry,employees,why_they_bought\n"
        "Verse Groothandel BV,versegroothandel.example,wholesale,120,Orders were retyped from email\n")


def test_best_clients_are_excluded_and_profiled_without_names(env):
    _write_best_clients(env)
    cfg = load_client(CLIENT)
    conn = db.connect()
    s = best_clients.import_best_clients(cfg, conn, fetcher=StubFetcher())
    assert s == {"clients": 1, "crawled": 1, "suppressed": 1, "in_prospect_list": 0}
    assert "versegroothandel.example" in db.suppressed_values(conn, CLIENT, "domain")
    assert "verse groothandel bv" in db.suppressed_values(conn, CLIENT, "company")
    profiles = best_clients.jev_profiles(cfg, conn)
    assert profiles[0]["why_they_bought"] and "Benelux" in profiles[0]["what_they_do"]
    assert "Verse Groothandel" not in json.dumps(profiles) and "versegroothandel" not in json.dumps(profiles)


def test_lookalike_question_score_and_tier(env):
    _write_best_clients(env)
    cfg = load_client(CLIENT)
    conn = db.connect()
    best_clients.import_best_clients(cfg, conn, fetcher=StubFetcher())
    item = {"name": "Groothandel BV", "industry": "Wholesale", "country": "NL", "employee_range": "51-200",
            "home_title": "Home", "home_excerpt": "We distribute parts", "job_titles": []}
    state, questions, _ = l2_jev.build_request(cfg, item, best_clients.jev_profiles(cfg, conn))
    assert state["sellers_best_customers"] and questions["lookalike"]["type"] == "score"
    _, no_best, _ = l2_jev.build_request(cfg, item)
    assert "lookalike" not in no_best
    # Very similar to a best client: Tier 2 without a buying signal; not similar: Tier 3
    assert l2_prefilter.tier_for(cfg, fit=70, signal=0, lookalike=2.0) == "tier_2"
    assert l2_prefilter.tier_for(cfg, fit=70, signal=0, lookalike=0.0) == "tier_3"


def test_push_holds_parked_tiers(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    acc = _approved(conn, "Klein BV", "NL", "Cas", "cas@klein.example")
    conn.execute("UPDATE accounts SET status='tier_3' WHERE id=?", (acc,))
    conn.commit()
    assert l6_send.plan_push(cfg, conn).held == {"tier_not_in_send_plan:tier_3": 1}
