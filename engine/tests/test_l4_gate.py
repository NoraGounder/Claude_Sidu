"""Layer 4 send gate with synthetic contacts."""

import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from gtm import db
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l4_gate

CLIENT = "the-marble-jar"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    return clients / CLIENT


def _account(conn, name, domain, tier):
    cur = conn.execute("INSERT INTO accounts(client, name, domain, segments, source, status, first_seen, last_seen)"
                       " VALUES (?,?,?,?,?,?,?,?)", (CLIENT, name, domain, "[]", "t", tier, "t", "t"))
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at)"
                 " VALUES (?,?,?,?,?,?,?)", (cur.lastrowid, 80, 40, tier, 1, 1, "t"))
    return cur.lastrowid


def _contact(conn, acc, first, email, status="DELIVERABLE", country="NL", days_old=1, source="FullEnrich people search"):
    ts = (NOW - timedelta(days=days_old)).isoformat()
    conn.execute(
        "INSERT INTO contacts(client, account_id, person_id, first_name, last_name, country, status, email,"
        " email_status, data_source, verified_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (CLIENT, acc, first, first, "X", country, "email_found", email, status, source, ts, ts, ts))


def _statuses(conn):
    return {r["first_name"]: (r["status"], r["status_reason"]) for r in conn.execute("SELECT * FROM contacts")}


def test_gate_rules(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    a = _account(conn, "Groothandel BV", "groothandel.example", "tier_1")
    t3 = _account(conn, "Klein BV", "klein.example", "tier_3")
    _contact(conn, a, "Anna", "anna@groothandel.example")
    _contact(conn, a, "Info", "info@groothandel.example")
    _contact(conn, a, "Gmail", "someone@gmail.com")
    _contact(conn, a, "Other", "bram@andere-firma.example")
    _contact(conn, a, "Old", "old@groothandel.example", days_old=60)
    _contact(conn, a, "German", "hans@groothandel.example", country="DE")
    _contact(conn, a, "Bad", "bad@groothandel.example", status="INVALID")
    _contact(conn, t3, "CatchT3", "piet@klein.example", status="CATCH_ALL")
    _contact(conn, a, "Sub", "eva@nl.groothandel.example")
    conn.commit()

    l4_gate.run(cfg, conn, now=NOW)
    s = _statuses(conn)
    # Sender consent is still pending in client.yaml, so even clean contacts are held
    assert s["Anna"] == ("held", "sender_consent_pending")
    assert s["Sub"] == ("held", "sender_consent_pending")          # subdomain of the company's domain is fine
    assert s["Info"] == ("rejected_l4", "role_address")
    assert s["Gmail"] == ("rejected_l4", "free_mail_address")
    assert s["Other"][1].startswith("domain_mismatch")
    assert s["Old"] == ("held", "stale_email:re-check with MillionVerifier")
    assert s["German"] == ("rejected_l4", "contact_country:DE")
    assert s["Bad"] == ("rejected_l4", "email_status:INVALID")
    assert s["CatchT3"] == ("held", "catch_all_not_allowed_for_tier_3")


def test_consent_and_catch_all_cap(env):
    client_file = env / "client.yaml"
    data = yaml.safe_load(client_file.read_text())
    data["sender"]["consent_to_send_in_name"] = "granted"
    client_file.write_text(yaml.safe_dump(data))
    cfg = load_client(CLIENT)
    conn = db.connect()
    a = _account(conn, "Groothandel BV", "groothandel.example", "tier_1")
    for n in range(9):
        _contact(conn, a, f"ok{n}", f"ok{n}@groothandel.example")
    _contact(conn, a, "catch1", "c1@groothandel.example", status="CATCH_ALL")
    _contact(conn, a, "catch2", "c2@groothandel.example", status="CATCH_ALL")
    db.add_suppression(conn, CLIENT, "email", "ok8@groothandel.example", "asked to stop")
    conn.commit()

    res = l4_gate.run(cfg, conn, now=NOW)
    s = _statuses(conn)
    assert s["ok0"] == ("ready", None)
    assert s["ok8"] == ("rejected_l4", "suppressed")
    # 10 ready candidates x 15% = 1 catch-all allowed
    assert sorted([s["catch1"][0], s["catch2"][0]]) == ["held", "ready"]
    assert res.counts == {"ready": 9, "held": 1, "rejected_l4": 1}


def test_recheck_uses_millionverifier_for_stale_only(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    a = _account(conn, "Groothandel BV", "groothandel.example", "tier_1")
    _contact(conn, a, "Fresh", "fresh@groothandel.example")
    _contact(conn, a, "Old", "old@groothandel.example", days_old=60)
    _contact(conn, a, "Dead", "dead@groothandel.example", days_old=90)
    conn.commit()

    class StubMV:
        def __init__(self):
            self.checked = []

        def verify(self, email):
            self.checked.append(email)
            return {"result": "invalid" if email.startswith("dead") else "ok", "role": False, "free": False}

    mv = StubMV()
    l4_gate.run(cfg, conn, recheck=True, mv=mv, now=NOW)
    assert sorted(mv.checked) == ["dead@groothandel.example", "old@groothandel.example"]
    s = _statuses(conn)
    assert s["Old"] == ("held", "sender_consent_pending")       # now fresh and valid
    assert s["Dead"] == ("rejected_l4", "email_status:INVALID")


def test_related_group_domains_pass():
    assert l4_gate.related_domain("bunzl.com", "bunzlretail.nl")
    assert l4_gate.related_domain("nl.groothandel.example", "groothandel.example")
    assert not l4_gate.related_domain("andere-firma.example", "groothandel.example")
    assert not l4_gate.related_domain("abc.nl", "abcdef.nl")          # brand too short to trust
