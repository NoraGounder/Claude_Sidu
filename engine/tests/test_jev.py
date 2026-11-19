"""Jev 1.14 policy and Decisions API client, with a stub HTTP session (no network, no cost)."""

import json
import shutil

import pytest

from gtm import db
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l2_jev
from gtm.sources.jev import JevClient, JevPolicyError, JevUnavailable, check_policy, scrub

CLIENT = "the-marble-jar"
GOOD_AI = {"model": "typesafe/jev-1.14", "endpoint": "https://openrouter.ai/api/alpha/decisions",
           "fallback": "none", "api_key_env": "OPENROUTER_API_KEY"}


class Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class StubSession:
    """Answers every question: titles containing 'admin' or 'order' are admin work."""

    def __init__(self, model="typesafe/jev-1.14-20261014", status=200, fail_on=None):
        self.headers = {}
        self.model, self.status, self.fail_on = model, status, fail_on
        self.bodies = []

    def post(self, url, json=None, timeout=None):
        self.bodies.append((url, json))
        if self.fail_on and self.fail_on in str(json["state"]):
            return Resp(503, {"error": {"message": "overloaded, key sk-or-v1-abcdef123 keys/9f8e7d"}})
        if self.status != 200:
            return Resp(self.status, {"error": {"message": "nope"}})
        answers = {}
        for key, q in json["questions"].items():
            if key == "not_a_buyer":
                answers[key] = {"type": "noul", "noul": 0.9 if "Media" in str(json["state"].get("company")) else 0.05}
            elif key == "icp_fit":
                answers[key] = {"type": "score", "score": 1.6, "confidence": 0.4,
                                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}}
            else:
                parts = q["instructions"].lower().split('"')
                title = parts[1] if len(parts) > 2 else ""
                answers[key] = {"type": "noul", "noul": 0.9 if ("admin" in title or "order" in title) else 0.1}
        return Resp(200, {"model": self.model, "answers": answers, "id": "gen-dec-test",
                          "usage": {"input_tokens": 400, "output_tokens": 30, "cost": 0.000017}})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    return tmp_path


def _scored(conn, name, titles, status="tier_3"):
    cur = conn.execute(
        "INSERT INTO accounts(client, name, industry, country, employee_range, website, segments, source, status,"
        " first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (CLIENT, name, "Wholesale", "NL", "51-200", None, '["wholesale_nl"]', "test", status, "t", "t"))
    conn.execute(
        "INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, job_link_count, job_titles,"
        " flags, breakdown, scored_at, home_title, home_excerpt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cur.lastrowid, 70, 0, status, 1, 1, len(titles), json.dumps(titles), "[]", "{}", "t", name, "Wij zijn..."))
    return cur.lastrowid


def test_project_config_passes_the_policy(env):
    cfg = load_client(CLIENT)
    check_policy(cfg.ai)
    assert cfg.ai["model"] == "typesafe/jev-1.14"


@pytest.mark.parametrize("model", ["typesafe/jev-router", "~typesafe/jev-latest", "openrouter/auto",
                                   "google/gemini-3.8-flash", "anthropic/claude-sonnet-5-5", "typesafe/jev-1.13"])
def test_policy_refuses_any_other_model(model):
    with pytest.raises(JevPolicyError):
        check_policy(GOOD_AI | {"model": model})


def test_policy_refuses_fallback_and_wrong_endpoint():
    with pytest.raises(JevPolicyError):
        check_policy(GOOD_AI | {"fallback": "anthropic/claude"})
    with pytest.raises(JevPolicyError):
        check_policy(GOOD_AI | {"endpoint": "https://openrouter.ai/api/v1/chat/completions"})


def test_answer_from_another_model_stops(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    client = JevClient(GOOD_AI, session=StubSession(model="google/gemini-3.8-flash"))
    with pytest.raises(JevUnavailable, match="not typesafe/jev-1.14"):
        client.decide({"x": 1}, {"q": {"type": "noul", "instructions": "?", "criteria": {"true": "a", "false": "b"}}})


def test_request_goes_to_decisions_endpoint_with_jev_114(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    session = StubSession()
    client = JevClient(GOOD_AI, session=session)
    result = client.decide({"company": "X"}, {"not_a_buyer": {"type": "noul", "instructions": "?",
                                                             "criteria": {"true": "a", "false": "b"}}})
    url, body = session.bodies[0]
    assert url == "https://openrouter.ai/api/alpha/decisions" and body["model"] == "typesafe/jev-1.14"
    assert result.model_id == "typesafe/jev-1.14-20261014" and result.cost_usd == 0.000017


def test_scrub_hides_keys():
    out = scrub("Bearer sk-or-v1-abc123 at https://openrouter.ai/workspaces/x/keys/31366e8c")
    assert "sk-or" not in out and "31366e8c" not in out


def test_run_decides_logs_and_rescores(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    a = _scored(conn, "Voorbeeld Groothandel", ["Medewerker orderverwerking", "Chauffeur CE"])
    b = _scored(conn, "Branche Media BV", ["Redacteur"])
    conn.commit()
    jp = l2_jev.plan(cfg, conn)
    assert len(jp.items) == 2 and jp.est_cost == pytest.approx(0.0002)
    session = StubSession()
    totals = l2_jev.run(cfg, conn, jp, client=JevClient(cfg.ai, session=session), workers=1)

    assert totals["decided"] == 2 and totals["models"] == ["typesafe/jev-1.14-20261014"]
    calls = conn.execute("SELECT requested_model, model_id, input_tokens, output_tokens, cost_usd, status"
                         " FROM jev_calls").fetchall()
    assert [tuple(c) for c in calls] == [("typesafe/jev-1.14", "typesafe/jev-1.14-20261014", 400, 30, 0.000017,
                                          "succeeded")] * 2
    assert conn.execute("SELECT status FROM accounts WHERE id=?", (b,)).fetchone()[0] == "rejected_l2"
    row = conn.execute("SELECT signal, tier FROM l2_scores WHERE account_id=?", (a,)).fetchone()
    assert row["signal"] == 30
    # Already-decided accounts are not asked again
    assert l2_jev.plan(cfg, conn).items == []
    # No personal data in requests: company facts only
    assert all("@" not in json.dumps(body) for _, body in session.bodies)


def test_jev_failure_stops_the_run_without_switching_models(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _scored(conn, "Goed BV", ["Planner"])
    _scored(conn, "Kapot BV", ["Planner"])
    conn.commit()
    jp = l2_jev.plan(cfg, conn)
    session = StubSession(fail_on="Kapot BV")
    with pytest.raises(JevUnavailable) as exc:
        l2_jev.run(cfg, conn, jp, client=JevClient(cfg.ai, session=session), workers=1)
    assert "sk-or" not in str(exc.value)
    assert {body["model"] for _, body in session.bodies} == {"typesafe/jev-1.14"}
    failed = conn.execute("SELECT error FROM jev_calls WHERE status='failed'").fetchone()[0]
    assert "503" in failed and "sk-or" not in failed and "9f8e7d" not in failed
