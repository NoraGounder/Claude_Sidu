"""Layer 6 with a stub Smartlead API and stub Jev 1.14 (synthetic data, no network, nothing sent)."""

import json
import shutil

import pytest

from conftest import legacy_nl
from gtm import db
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l6_send
from gtm.sources.jev import JevClient
from gtm.sources.smartlead import SmartleadClient, SmartleadError, scrub

CLIENT = "the-marble-jar"


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


class StubSmartlead:
    def __init__(self, mailboxes=None, replies=None):
        self.calls = []
        self.mailboxes = mailboxes if mailboxes is not None else [
            {"id": 1, "from_email": "m@tmj-mail.example", "message_per_day": 15, "warmup_enabled": True},
            {"id": 2, "from_email": "x@tmj-mail.example", "message_per_day": 40, "warmup_enabled": True},
            {"id": 3, "from_email": "y@tmj-mail.example", "message_per_day": 15, "warmup_enabled": False}]
        self.replies = replies or {}
        self.leads_added = []

    def request(self, method, url, params=None, json=None, timeout=None):
        path = url.split("/api/v1")[1]
        self.calls.append((method, path, params, json))
        assert params["api_key"] == "test-key"
        if path == "/campaigns/create":
            return Resp(200, {"campaign": {"id": 900 + len([c for c in self.calls if c[1] == "/campaigns/create"])}})
        if path == "/email-accounts":
            return Resp(200, self.mailboxes)
        if path.endswith("/leads") and method == "POST":
            self.leads_added.extend(json["lead_list"])
            return Resp(200, {"ok": True})
        if path.endswith("/leads") and method == "GET":
            status = params.get("emailStatus")
            if status == "is_replied":
                return Resp(200, {"data": [{"lead": {"id": 55, "email": e}} for e in self.replies]})
            return Resp(200, {"data": []})
        if path.endswith("/message-history"):
            email = list(self.replies)[0]
            return Resp(200, {"history": [{"type": "SENT", "email_body": "Hi"},
                                          {"type": "REPLY", "time": "2026-11-20T10:00:00Z",
                                           "email_body": self.replies[email]}]})
        if path.endswith("/settings") and method == "PATCH":
            return Resp(405, {"error": "use POST"})
        return Resp(200, {"ok": True})


class StubJev:
    def __init__(self):
        self.headers, self.bodies = {}, []

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        text = json["state"]["reply_to_a_sales_email"].lower()
        cat = "unsubscribe" if "remove me" in text else "interested"
        return Resp(200, {"model": "typesafe/jev-1.14-20261014",
                          "answers": {"category": {"type": "choice", "choice": cat, "probabilities": {cat: 0.9}}},
                          "usage": {"input_tokens": 100, "output_tokens": 5, "cost": 0.000004}})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def make_env(tmp_path, monkeypatch):
    """Copy of the client config with a test sender, in a temporary clients and data folder."""
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    legacy_nl(clients / CLIENT)
    (clients / CLIENT / "private").mkdir()
    (clients / CLIENT / "private" / "sender.yaml").write_text("first_name: Sam\nfull_name: Sam Example\n")
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    return clients / CLIENT


def _approved(conn, company, country, first, email, contact_status="ready", draft_status="approved", rank=1, acc=None):
    if acc is None:
        cur = conn.execute("INSERT INTO accounts(client, name, domain, country, segments, source, status, first_seen,"
                           " last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                           (CLIENT, company, email.split("@")[1], country, "[]", "t", "tier_1", "t", "t"))
        acc = cur.lastrowid
    cur = conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, status, email,"
                       " email_status, data_source, rank, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (CLIENT, acc, first, first, "Tester", contact_status, email, "DELIVERABLE", "FullEnrich", rank,
                        "t", "t"))
    steps = [{"day": d, "body": f"Body {d} for {first}"} for d in (0, 3, 7, 14)]
    conn.execute("INSERT INTO drafts(client, contact_id, language, hook, process, subject, steps_json, facts_json,"
                 " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (CLIENT, cur.lastrowid, "en", "generic", "orders", f"Subject for {first}", json.dumps(steps), "{}",
                  draft_status, "t", "t"))
    conn.commit()
    return acc


def test_sequence_payload_uses_relative_delays_and_threads_followups():
    seq = l6_send.sequence_payload([0, 3, 7, 14])
    assert [s["seq_delay_details"]["delay_in_days"] for s in seq] == [0, 3, 4, 7]
    assert seq[0]["subject"] == "{{tmj_subject}}" and all(s["subject"] == "" for s in seq[1:])
    assert seq[2]["email_body"] == "{{tmj_email_3}}"


def test_scrub_hides_the_api_key():
    assert "secret123" not in scrub("GET https://server.smartlead.ai/api/v1/x?api_key=secret123&limit=1")
    with pytest.raises(SmartleadError):
        SmartleadClient(api_key="proxy-injected")


def test_plan_applies_every_guard(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    acc = _approved(conn, "Groothandel BV", "NL", "Anna", "anna@groothandel.example")
    _approved(conn, "Groothandel BV", "NL", "Bram", "bram@groothandel.example", rank=2, acc=acc)   # same company
    _approved(conn, "Klein BV", "NL", "Cas", "cas@klein.example", draft_status="needs_review")    # not approved
    _approved(conn, "Held BV", "NL", "Dirk", "dirk@held.example", contact_status="held")
    _approved(conn, "Duits GmbH", "DE", "Eva", "eva@duits.example")                              # no region
    _approved(conn, "Uk Ltd", "GB", "Finn", "finn@uk.example")
    db.add_suppression(conn, CLIENT, "email", "finn@uk.example", "asked to stop")
    conn.commit()
    plan = l6_send.plan_push(cfg, conn)
    assert [lead["email"] for lead in plan.eligible["nl"]] == ["anna@groothandel.example"]
    assert plan.held == {"another_contact_at_this_company_is_active": 1, "contact_not_ready:held": 1,
                         "no_region_for_country:DE": 1, "suppressed": 1}
    lead = plan.eligible["nl"][0]
    assert lead["custom_fields"]["tmj_email_1"] == "Body 0 for Anna" and lead["custom_fields"]["tmj_subject"]


def test_consent_is_required(env):
    path = env / "client.yaml"
    path.write_text(path.read_text().replace("consent_to_send_in_name: granted", "consent_to_send_in_name: pending"))
    cfg = load_client(CLIENT)
    conn = db.connect()
    _approved(conn, "Groothandel BV", "NL", "Anna", "anna@groothandel.example")
    plan = l6_send.plan_push(cfg, conn)
    assert plan.eligible == {} and plan.held == {"sender_consent_not_granted": 1}


def test_push_creates_paused_campaign_with_checked_mailboxes_and_never_starts(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _approved(conn, "Groothandel BV", "NL", "Anna", "anna@groothandel.example")
    stub = StubSmartlead()
    t = l6_send.push(cfg, conn, sl=SmartleadClient(api_key="test-key", session=stub))
    assert t["pushed"] == 1 and set(t["campaigns"]) == {"nl"}
    assert len(t["mailbox_problems"]) == 2                       # 40/day mailbox and no-warm-up mailbox refused
    paths = [(m, p) for m, p, _, _ in stub.calls]
    assert ("POST", "/campaigns/900/email-accounts") in paths or ("POST", "/campaigns/901/email-accounts") in paths
    link = next(j for m, p, _, j in stub.calls if p.endswith("/email-accounts") and m == "POST")
    assert link == {"email_account_ids": [1]}
    assert not any(p.endswith("/status") for _, p in paths)      # push never starts a campaign
    settings = next(j for m, p, _, j in stub.calls if p.endswith("/settings") and m == "POST")   # PATCH->POST fallback
    assert settings["track_settings"] == {"track_open": False, "track_click": False}
    assert settings["stop_lead_settings"]["stop_on_reply"] is True
    schedule = next(j for m, p, _, j in stub.calls if p.endswith("/schedule"))
    assert schedule["timezone"] == "Europe/Amsterdam" and schedule["days_of_the_week"] == [2, 3, 4]
    assert "_contact_id" not in stub.leads_added[0]              # internal fields never leave the engine
    assert l6_send.plan_push(cfg, conn).eligible == {}           # never uploaded twice


def test_sync_classifies_masked_replies_and_suppresses_unsubscribes(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _approved(conn, "Groothandel BV", "NL", "Anna", "anna@groothandel.example")
    sl_stub = StubSmartlead()
    sl = SmartleadClient(api_key="test-key", session=sl_stub)
    l6_send.push(cfg, conn, sl=sl)

    sl_stub.replies = {"anna@groothandel.example":
                       "Please remove me from your list. Anna Tester, +31 6 1234 5678, anna@groothandel.example"}
    jev_stub = StubJev()
    t = l6_send.sync(cfg, conn, sl=sl, jev=JevClient(cfg.ai, session=jev_stub))
    assert t["replies"] == 1 and t["categories"] == {"unsubscribe": 1} and t["unsubscribed"] == 1
    sent = json.dumps(jev_stub.bodies)
    assert "Anna" not in sent and "1234" not in sent and "@groothandel" not in sent
    assert {b["model"] for b in jev_stub.bodies} == {"typesafe/jev-1.14"}
    assert "anna@groothandel.example" in db.suppressed_values(conn, CLIENT, "email")
    assert any(p == "/leads/block-list" for _, p, _, _ in sl_stub.calls)
    # The same reply is not processed twice
    assert l6_send.sync(cfg, conn, sl=sl, jev=JevClient(cfg.ai, session=jev_stub))["replies"] == 0
