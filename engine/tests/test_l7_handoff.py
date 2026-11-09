"""Layer 7 with stub Smartlead, Jev 1.14 and HubSpot (synthetic data, no network, nothing sent)."""

import json

import pytest
from test_l6_send import CLIENT, Resp, StubJev, StubSmartlead, _approved, make_env

from gtm import best_clients, db, learn
from gtm.config import load_client
from gtm.layers import l6_send, l7_handoff
from gtm.sources.hubspot import HubSpotClient, HubSpotError
from gtm.sources.jev import JevClient
from gtm.sources.smartlead import SmartleadClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


class StubHubSpot:
    def __init__(self):
        self.headers, self.calls, self.next_id = {}, [], 100

    def request(self, method, url, json=None, timeout=None):
        path = url.split("api.hubapi.com")[1]
        self.calls.append((method, path, json))
        assert self.headers["Authorization"] == "Bearer proxy-injected"
        if path.endswith("/search"):
            return Resp(200, {"results": []})
        if method == "POST":
            self.next_id += 1
            return Resp(201, {"id": str(self.next_id)})
        return Resp(200, {"id": path.rsplit("/", 1)[-1]})


def _replied(env, text):
    cfg = load_client(CLIENT)
    conn = db.connect()
    acc = _approved(conn, "Groothandel BV", "NL", "Anna", "anna@groothandel.example")
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, job_titles, breakdown,"
                 " scored_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (acc, 80, 50, "tier_1", 1, 0, json.dumps(["Order entry clerk"]),
                  json.dumps({"signals": {"admin_job_ad": 30}}), "t"))
    conn.execute("INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
                 (acc, "L2", "admin_job_ad", "job title: Order entry clerk", "https://groothandel.example/jobs", "", "t"))
    conn.commit()
    sl_stub = StubSmartlead()
    sl = SmartleadClient(api_key="test-key", session=sl_stub)
    l6_send.push(cfg, conn, sl=sl)
    sl_stub.replies = {"anna@groothandel.example": text}
    l6_send.sync(cfg, conn, sl=sl, jev=JevClient(cfg.ai, session=StubJev()))
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='anna@groothandel.example'").fetchone()[0]
    return cfg, conn, contact_id


def test_interested_reply_becomes_a_deal_and_a_brief(env):
    cfg, conn, cid = _replied(env, "Sounds useful, can we talk on Thursday?")
    t = l7_handoff.handoff(cfg, conn)
    assert t["briefs"] == 1 and t["closed"] == 0
    with open(t["paths"][0], encoding="utf-8") as fh:
        brief = fh.read()
    assert "Groothandel BV" in brief and "Order entry clerk" in brief and "https://groothandel.example/jobs" in brief
    assert "Sounds useful" in brief and "Thanks Anna" in brief
    assert "Tuesday or Thursday" in brief                     # no booking link yet: proposes times
    assert "free" not in brief.lower() and "fixed price" not in brief.lower()
    assert conn.execute("SELECT stage FROM deals WHERE contact_id=?", (cid,)).fetchone()[0] == "interested"
    assert l7_handoff.handoff(cfg, conn)["briefs"] == 0       # each reply handled once


def test_unsubscribe_reply_is_closed_without_a_deal(env):
    cfg, conn, _ = _replied(env, "Please remove me from your list.")
    t = l7_handoff.handoff(cfg, conn)
    assert (t["briefs"], t["closed"]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 0


def test_outcomes_feed_revenue_learning_and_lookalikes(env):
    cfg, conn, cid = _replied(env, "Sounds useful, can we talk on Thursday?")
    l7_handoff.handoff(cfg, conn)
    assert l7_handoff.record_outcome(cfg, conn, cid, "not a fit")["stage"] == "not_a_fit"   # Mithun's words
    with pytest.raises(ValueError):
        l7_handoff.record_outcome(cfg, conn, cid, "maybe")
    deal = l7_handoff.record_outcome(cfg, conn, cid, "won", value_eur=24000)
    assert deal["stage"] == "won" and deal["value_eur"] == 24000
    p = l7_handoff.pipeline(cfg, conn)
    assert p["won"] == 1 and p["won_eur"] == 24000 and p["meetings_held"] == 1
    report = learn.outcomes(cfg, conn)
    assert report["signal"]["admin_job_ad"]["won"] == 1 and report["signal"]["admin_job_ad"]["revenue_eur"] == 24000
    # The won company becomes a lookalike (without its name) and is never cold-emailed again
    assert "groothandel.example" in db.suppressed_values(conn, CLIENT, "domain")
    profiles = best_clients.jev_profiles(cfg, conn)
    assert profiles and "Groothandel" not in json.dumps(profiles)


def test_crm_mirror_creates_then_updates_and_never_deletes(env):
    cfg, conn, cid = _replied(env, "Sounds useful, can we talk on Thursday?")
    l7_handoff.handoff(cfg, conn)
    plan = l7_handoff.plan_crm(cfg, conn)
    assert len(plan.creates) == 1 and not plan.updates
    stub = StubHubSpot()
    hs = HubSpotClient(token="proxy-injected", session=stub)
    assert l7_handoff.sync_crm(cfg, conn, plan, hs) == {"created": 1, "updated": 0}
    deal_body = next(j for m, p, j in stub.calls if m == "POST" and p == "/crm/v3/objects/deals")
    assert deal_body["properties"]["dealstage"] == "appointmentscheduled"
    assert {a["types"][0]["associationTypeId"] for a in deal_body["associations"]} == {3, 5}
    assert "FullEnrich" in deal_body["properties"]["description"]
    assert l7_handoff.plan_crm(cfg, conn).creates == []      # nothing to do until something changes
    l7_handoff.record_outcome(cfg, conn, cid, "won", value_eur=24000)
    conn.execute("UPDATE deals SET updated_at='9999' WHERE contact_id=?", (cid,))   # later than the last sync
    stub.calls.clear()
    plan = l7_handoff.plan_crm(cfg, conn)
    assert l7_handoff.sync_crm(cfg, conn, plan, hs) == {"created": 0, "updated": 1}
    assert stub.calls[0][0] == "PATCH" and stub.calls[0][2]["properties"]["dealstage"] == "closedwon"
    assert not any(m == "DELETE" for m, _, _ in stub.calls)


def test_hubspot_needs_a_token(monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    with pytest.raises(HubSpotError):
        HubSpotClient()


def test_retention_follows_the_dpa_schedule(env):
    from datetime import datetime, timedelta, timezone

    from gtm import retention

    cfg, conn, cid = _replied(env, "Sounds useful, can we talk on Thursday?")
    l7_handoff.handoff(cfg, conn)
    acc = conn.execute("SELECT account_id FROM contacts WHERE id=?", (cid,)).fetchone()[0]
    old = "2020-01-01T00:00:00+00:00"
    conn.execute("INSERT INTO contacts(client, account_id, first_name, status, data_source, created_at, updated_at)"
                 " VALUES (?,?,?,?,?,?,?)", (CLIENT, acc, "Old", "candidate", "FullEnrich", old, old))
    _approved(conn, "Stil BV", "NL", "Sem", "sem@stil.example")
    stub = StubSmartlead()
    l6_send.push(cfg, conn, sl=SmartleadClient(api_key="test-key", session=stub))
    db.add_suppression(conn, CLIENT, "email", "sem@stil.example", "asked to stop")
    conn.commit()
    later = datetime.now(timezone.utc) + timedelta(days=400)
    dry = retention.run(cfg, conn, now=later)
    assert dry["applied"] is False and dry["not_emailed"] >= 1 and dry["no_reply"] == 1 and dry["reply_texts"] == 1
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE first_name='Old'").fetchone()[0] == 1   # dry run
    retention.run(cfg, conn, apply=True, now=later)
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE first_name IN ('Old','Sem')").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE id=?", (cid,)).fetchone()[0] == 1       # has a deal
    assert conn.execute("SELECT text FROM replies").fetchone()[0] is None                          # text emptied
    assert "sem@stil.example" in db.suppressed_values(conn, CLIENT, "email")                       # opt-out kept
