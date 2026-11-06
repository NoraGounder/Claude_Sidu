"""AI review through OpenRouter, with a stub client (no network, no cost)."""

import json
import shutil

import pytest

from gtm import budget, db
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l2_ai_review
from gtm.sources.openrouter import Decision

CLIENT = "the-marble-jar"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _scored(conn, name, titles, fit=80, flags=("review_job_titles",)):
    cur = conn.execute(
        "INSERT INTO accounts(client, name, segments, source, status, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?)", (CLIENT, name, '["logistics_nl"]', "test", "tier_3", "t", "t"))
    conn.execute(
        "INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, careers_url, job_link_count,"
        " job_titles, flags, breakdown, scored_at, home_title) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cur.lastrowid, fit, 0, "tier_3", 1, 1, "https://x.example/vacatures", len(titles),
         json.dumps(titles), json.dumps(list(flags)), json.dumps({"fit": {}, "signals": {}}), "t", name))
    return cur.lastrowid


class StubRouter:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def decide(self, model, system, user, schema_name, schema):
        self.calls.append(user)
        return Decision(data=self.answer(user), cost_usd=0.0012, model_used="stub/model")


def test_review_validates_and_applies(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    a = _scored(conn, "Voorbeeld Groothandel", ["Medewerker orderverwerking", "Chauffeur CE"])
    b = _scored(conn, "Branche Media BV", ["Redacteur"])
    c = _scored(conn, "Al Gereviewd", ["Planner"], flags=("reviewed:claude",))
    conn.commit()

    def answer(user):
        return {"reviews": [
            {"account_id": a, "admin_roles": ["Medewerker orderverwerking", "Invented Title"],
             "not_a_buyer": False, "reason": ""},
            {"account_id": b, "admin_roles": [], "not_a_buyer": True, "reason": "trade magazine"},
            {"account_id": 99999, "admin_roles": ["x"], "not_a_buyer": True, "reason": "not in batch"},
        ]}

    rp = l2_ai_review.plan(cfg, conn, include_all=True, batch_size=20, limit=None)
    assert [i["account_id"] for i in rp.items] == [a, b]          # already-reviewed account skipped
    assert rp.est_cost == 0.02
    stub = StubRouter(answer)
    totals = l2_ai_review.run(cfg, conn, rp, client=stub)

    assert totals["batches"] == 1 and totals["reviewed"] == 2 and totals["dropped"] == 1
    assert "Chauffeur CE" in stub.calls[0] and "@" not in stub.calls[0]   # company facts only
    row = conn.execute("SELECT signal, tier FROM l2_scores WHERE account_id=?", (a,)).fetchone()
    assert (row["signal"], row["tier"]) == (30, "tier_2")
    ev = conn.execute("SELECT quote FROM evidence WHERE account_id=?", (a,)).fetchall()
    assert [e["quote"] for e in ev] == ["Medewerker orderverwerking"]     # invented title rejected
    assert conn.execute("SELECT status FROM accounts WHERE id=?", (b,)).fetchone()[0] == "rejected_l2"
    # Actual reported cost is logged, not the estimate
    assert db.month_spend(conn, CLIENT, "openrouter") == pytest.approx(0.0012)


def test_review_respects_budget(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _scored(conn, "Iets BV", ["Planner"])
    conn.commit()
    rid = db.start_run(conn, CLIENT, "L2-AI", "openrouter", "earlier", 5.0, {})
    db.finish_run(conn, rid, "succeeded", 1, 4.99)
    rp = l2_ai_review.plan(cfg, conn, include_all=False, batch_size=20, limit=None)
    with pytest.raises(budget.BudgetExceeded):
        l2_ai_review.run(cfg, conn, rp, client=StubRouter(lambda u: {"reviews": []}))
