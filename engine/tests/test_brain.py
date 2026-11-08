"""GTM brain context for Jev 1.14 and the outcome report (synthetic data only)."""

import json

import pytest
from test_l6_send import CLIENT, StubJev, StubSmartlead, _approved, make_env

from gtm import brain, db, learn
from gtm.config import load_client
from gtm.layers import l2_jev, l6_send
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
