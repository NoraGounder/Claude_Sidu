"""Layer 3 with stub FullEnrich and Jev sessions (synthetic people, no network, no cost)."""

import json
import shutil

import pytest

from gtm import db
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l3_contacts
from gtm.sources.fullenrich import FullEnrichClient
from gtm.sources.jev import JevClient, JevUnavailable

CLIENT = "the-marble-jar"


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, json.dumps(payload)

    def json(self):
        return self._payload


def person(pid, first, last, title):
    return {"id": pid, "first_name": first, "last_name": last, "full_name": f"{first} {last}",
            "employment": {"current": {"title": title}}, "location": {"country_code": "NL"},
            "social_profiles": {"professional_network": {"url": f"https://www.linkedin.com/in/{pid}"}}}


PEOPLE = {
    "groothandel.example": [person("p1", "Anna", "Jansen", "Operations Manager"),
                            person("p2", "Bram", "de Vries", "Financieel Directeur"),
                            person("p3", "Chris", "Bakker", "Assistant Logistics Coordinator"),
                            person("p4", "Dina", "Smit", "Stagiair Finance")],
    "groot.example": [person("p5", "Eva", "Visser", "Algemeen Directeur"),
                      person("p6", "Frank", "Mulder", "COO")],
}


class StubFE:
    def __init__(self):
        self.headers, self.posts = {}, []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if url.endswith("/people/search"):
            domain = json["current_company_domains"][0]["value"]
            people = PEOPLE.get(domain, [])[: json["limit"]]
            return Resp(200, {"people": people, "metadata": {"credits": 0.25 * len(people), "total": len(people)}})
        if url.endswith("/contact/enrich/bulk"):
            self.batch = json["data"]
            return Resp(200, {"enrichment_id": "enr-1"})
        raise AssertionError(url)

    def get(self, url, timeout=None):
        data = []
        for c in self.batch:
            email = None if c["first_name"] == "Bram" else f"{c['first_name'].lower()}@{c['domain']}"
            status = "CATCH_ALL" if c["first_name"] == "Frank" else "DELIVERABLE"
            data.append({"custom": c["custom"], "contact_info": {
                "most_probable_work_email": {"email": email, "status": status} if email else {}}})
        return Resp(200, {"status": "FINISHED", "cost": {"credits": sum(1 for d in data if
                                                                           d["contact_info"]["most_probable_work_email"])},
                          "data": data})


class StubJev:
    """Higher relevance for operations and finance leaders than for the MD."""

    def __init__(self, fail=False):
        self.headers, self.bodies, self.fail = {}, [], fail

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        if self.fail:
            return Resp(503, {"error": "down"})
        answers = {}
        for key, q in json["questions"].items():
            title = q["instructions"].split('"')[1].lower()
            p = 0.9 if ("operations" in title or "coo" == title) else 0.8 if "financ" in title else 0.6
            answers[key] = {"type": "noul", "noul": p}
        return Resp(200, {"model": "typesafe/jev-1.14-20261014", "answers": answers,
                          "usage": {"input_tokens": 300, "output_tokens": 20, "cost": 0.000013}})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    monkeypatch.setenv("FULLENRICH_API_KEY", "proxy-injected")
    return tmp_path


def _account(conn, name, domain, tier, rng):
    cur = conn.execute(
        "INSERT INTO accounts(client, name, domain, employee_range, segments, source, status, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?)", (CLIENT, name, domain, rng, '["wholesale_nl"]', "t", tier, "t", "t"))
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, scored_at)"
                 " VALUES (?,?,?,?,?,?,?)", (cur.lastrowid, 80, 30 if tier != "tier_3" else 0, tier, 1, 1, "t"))
    return cur.lastrowid


def test_title_matching_is_whole_word(env):
    cfg = load_client(CLIENT)
    assert l3_contacts.persona_of(cfg, "COO") == "operations"
    assert l3_contacts.persona_of(cfg, "Assistant Logistics Coordinator") is None
    assert l3_contacts.persona_of(cfg, "Financieel Directeur") == "finance"
    assert l3_contacts.persona_of(cfg, "Algemeen Directeur") == "owner_led"


def test_people_then_emails_end_to_end(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    a = _account(conn, "Groothandel BV", "groothandel.example", "tier_2", "51-200")
    b = _account(conn, "Groot BV", "groot.example", "tier_3", "201-500")
    conn.commit()

    cp = l3_contacts.plan(cfg, conn)
    assert [x["id"] for x in cp.accounts] == [a, b]              # Tier 2 before Tier 3
    assert cp.est_search_cost == pytest.approx(2 * 4 * 0.01375)

    fe_session, jev_session = StubFE(), StubJev()
    fe = FullEnrichClient(session=fe_session)
    t = l3_contacts.find_people(cfg, conn, cp, fe=fe, jev=JevClient(cfg.ai, session=jev_session))
    assert t["people_returned"] == 6 and t["candidates"] == 3 and t["selected"] == 3

    rows = {r["first_name"]: dict(r) for r in conn.execute("SELECT * FROM contacts")}
    assert set(rows) == {"Anna", "Bram", "Frank"}                # coordinator + intern dropped, MD of 201-500 dropped
    assert rows["Anna"]["status"] == rows["Bram"]["status"] == "selected"      # Tier 2: two contacts
    assert rows["Frank"]["status"] == "selected" and rows["Frank"]["data_source"].startswith("FullEnrich")
    # Jev only ever saw job titles, never names
    sent = json.dumps(jev_session.bodies)
    assert "Anna" not in sent and "Jansen" not in sent and "Operations Manager" in sent
    assert {b["model"] for b in jev_session.bodies} == {"typesafe/jev-1.14"}
    assert l3_contacts.plan(cfg, conn).accounts == []            # never searched twice

    e = l3_contacts.find_emails(cfg, conn, fe=fe)
    assert (e["requested"], e["found"], e["catch_all"], e["not_found"]) == (3, 1, 1, 1)
    emails = {r["first_name"]: (r["status"], r["email"], r["email_status"]) for r in conn.execute(
        "SELECT first_name, status, email, email_status FROM contacts")}
    assert emails["Anna"] == ("email_found", "anna@groothandel.example", "DELIVERABLE")
    assert emails["Frank"] == ("email_found", "frank@groot.example", "CATCH_ALL")
    assert emails["Bram"] == ("no_email", None, None)
    assert db.month_spend(conn, CLIENT, "fullenrich") == pytest.approx((6 * 0.25 + 2) * 0.055)   # 6 people returned + 2 emails found


def test_jev_failure_stops_people_search(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _account(conn, "Groothandel BV", "groothandel.example", "tier_2", "51-200")
    conn.commit()
    cp = l3_contacts.plan(cfg, conn)
    with pytest.raises(JevUnavailable):
        l3_contacts.find_people(cfg, conn, cp, fe=FullEnrichClient(session=StubFE()),
                                jev=JevClient(cfg.ai, session=StubJev(fail=True)))
    assert conn.execute("SELECT status FROM runs WHERE layer='L3-search'").fetchone()[0] == "failed"
    assert conn.execute("SELECT COUNT(*) FROM jev_calls WHERE status='failed'").fetchone()[0] == 1
