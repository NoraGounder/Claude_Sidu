"""Layer 5 drafts with a stub Jev 1.14 session (synthetic data, no network)."""

import csv
import json
import shutil

import pytest

from gtm import db
from gtm.config import REPO_ROOT, load_client
from gtm.layers import l5_copy
from gtm.sources.jev import JevClient

CLIENT = "the-marble-jar"


class Resp:
    def __init__(self, payload):
        self.status_code, self._payload, self.text = 200, payload, json.dumps(payload)

    def json(self):
        return self._payload


class StubJev:
    def __init__(self, unsupported=0.05):
        self.headers, self.bodies, self.unsupported = {}, [], unsupported

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        answers = {}
        for key, q in json["questions"].items():
            if key == "process":
                pick = "invoices" if "financ" in str(json["state"].get("contact_job_title", "")).lower() else "orders"
                answers[key] = {"type": "choice", "choice": pick, "probabilities": {pick: 0.8}}
            elif key == "angle":
                first = list(q["criteria"])[0]
                answers[key] = {"type": "choice", "choice": first, "probabilities": {first: 0.7}}
            else:
                answers[key] = {"type": "noul", "noul": self.unsupported}
        return Resp({"model": "typesafe/jev-1.14-20261014", "answers": answers,
                     "usage": {"input_tokens": 500, "output_tokens": 10, "cost": 0.00002}})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    clients = tmp_path / "clients"
    shutil.copytree(REPO_ROOT / "clients" / CLIENT, clients / CLIENT, ignore=shutil.ignore_patterns("private"))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    return clients / CLIENT


def _setup(conn, name="Voorbeeld Groothandel B.V.", titles=None, dutch=1, evidence=()):
    titles = titles if titles is not None else ["Administratief Medewerker Crediteuren (32-40 uur)", "Chauffeur CE"]
    cur = conn.execute("INSERT INTO accounts(client, name, domain, industry, segments, source, status, first_seen,"
                       " last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                       (CLIENT, name, "voorbeeld.example", "Wholesale", "[]", "t", "tier_1", "t", "t"))
    acc = cur.lastrowid
    conn.execute("INSERT INTO l2_scores(account_id, fit, signal, tier, reachable, dutch_site, careers_url, job_titles,"
                 " scored_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (acc, 90, 60, "tier_1", 1, dutch, "https://voorbeeld.example/vacatures", json.dumps(titles), "t"))
    for signal, label, url, quote in evidence:
        conn.execute("INSERT INTO evidence(account_id, layer, signal, label, url, quote, found_at) VALUES (?,?,?,?,?,?,?)",
                     (acc, "L2", signal, label, url, quote, "t"))
    conn.execute("INSERT INTO contacts(client, account_id, person_id, first_name, last_name, title, persona, status,"
                 " status_reason, email, email_status, data_source, created_at, updated_at)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (CLIENT, acc, "p1", "ANNA", "Jansen", "Financieel Directeur", "finance", "held",
                  "sender_consent_pending", "anna@voorbeeld.example", "DELIVERABLE", "FullEnrich", "t", "t"))
    conn.commit()
    return acc


def test_cleaning():
    assert l5_copy.clean_title("Administratief Medewerker Crediteuren (32-40 uur)") == "administratief medewerker crediteuren"
    assert l5_copy.clean_title("Medewerker Orderverwerking - Breda") == "medewerker orderverwerking"
    assert l5_copy.clean_title("SAP Key User Finance") == "SAP Key User Finance"
    slogan = "Customer Service Export Representative, Antwerpen/België Ben jij de documentatie kanjer? De perfectionist"
    assert l5_copy.clean_title(slogan) == "customer service export representative"
    assert not l5_copy.usable_title("medewerker administratie en planning voor onze vestiging in Breda")
    assert l5_copy.clean_company("Voorbeeld Groothandel B.V.") == "Voorbeeld Groothandel"
    assert l5_copy.clean_company("Roll Group") == "Roll Group"
    assert l5_copy.clean_first_name("ANNA") == "Anna"


def _dutch_default(client_dir):
    import yaml
    path = client_dir / "client.yaml"
    data = yaml.safe_load(path.read_text())
    data["language"]["default"] = "nl"
    path.write_text(yaml.safe_dump(data))


def test_default_language_is_english_even_for_dutch_companies(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    acc = _setup(conn)
    conn.execute("UPDATE accounts SET country='NL' WHERE id=?", (acc,))
    conn.commit()
    l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=StubJev()))
    d = conn.execute("SELECT * FROM drafts").fetchone()
    body = json.loads(d["steps_json"])[0]["body"]
    assert d["language"] == "en"
    assert "I saw the administratief medewerker crediteuren vacancy at Voorbeeld Groothandel." in body
    assert "Verlengde Poolseweg 16, 4818 CL Breda" in body          # postal address in the footer


def test_draft_uses_only_facts_and_preview_without_sender(env):
    _dutch_default(env)
    cfg = load_client(CLIENT)
    conn = db.connect()
    _setup(conn, evidence=[("erp_mention", "Exact", "https://voorbeeld.example/vacatures/x", "…Exact Online…")])
    stub = StubJev()
    t = l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=stub))
    assert t["drafted"] == 1 and t["preview"] == 1               # no private/sender.yaml yet

    d = conn.execute("SELECT * FROM drafts").fetchone()
    steps, facts = json.loads(d["steps_json"]), json.loads(d["facts_json"])
    assert d["hook"] == "admin_job_ad" and d["process"] == "invoices" and d["language"] == "nl"
    assert facts["job_title"]["value"] == "administratief medewerker crediteuren"
    assert facts["job_title"]["source"] == "https://voorbeeld.example/vacatures"
    assert facts["erp"]["value"] == "Exact"
    body = steps[0]["body"]
    assert "Ik zag dat Voorbeeld Groothandel een administratief medewerker crediteuren zoekt. Hoeveel van dat werk is gegevens overtypen van de ene plek naar de andere?" in body
    assert body.splitlines()[0].endswith("Anna,")
    assert "Je zakelijke contactgegevens vond ik via LinkedIn en FullEnrich" in body     # GDPR line
    assert "http" not in body and "themarblejar.io" not in body                         # no links in email 1
    assert [s["day"] for s in steps] == [0, 3, 7, 14]
    assert d["subject"] == "vacature administratief medewerker crediteuren"
    # Jev saw no names or emails
    sent = json.dumps(stub.bodies)
    assert "Anna" not in sent and "Jansen" not in sent and "@" not in sent
    assert {b["model"] for b in stub.bodies} == {"typesafe/jev-1.14"}


def test_generic_hook_and_english_when_no_facts(env):
    cfg = load_client(CLIENT)
    conn = db.connect()
    _setup(conn, titles=["Welder"], dutch=0)
    l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=StubJev()))
    d = conn.execute("SELECT * FROM drafts").fetchone()
    assert d["hook"] == "generic" and d["language"] == "en"
    assert "I found your business contact details via LinkedIn and FullEnrich" in json.loads(d["steps_json"])[0]["body"]


def test_fact_check_flag_and_review_round_trip(env, tmp_path):
    _dutch_default(env)          # this test edits Dutch text
    (env / "private").mkdir()
    (env / "private" / "sender.yaml").write_text("first_name: Sam\nfull_name: Sam Example\n")
    cfg = load_client(CLIENT)
    conn = db.connect()
    _setup(conn)
    l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=StubJev(unsupported=0.6)))
    d = conn.execute("SELECT * FROM drafts").fetchone()
    assert d["status"] == "needs_review" and "Sam" in json.loads(d["steps_json"])[0]["body"]

    path, n = l5_copy.export_review(cfg, conn, str(tmp_path / "review.csv"))
    assert n == 1
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert rows[0]["jev_fact_check"] == "unsupported claim p=0.60"

    # Reviewer approves with an edit to email 2, then tries removing the GDPR line in a second file
    rows[0]["decision"] = "approve"
    rows[0]["email_2"] = rows[0]["email_2"].replace("nuttig", "handig")
    with open(tmp_path / "back.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    c = l5_copy.import_review(cfg, conn, str(tmp_path / "back.csv"))
    assert c["approved"] == 1 and not c["errors"]
    d = conn.execute("SELECT * FROM drafts").fetchone()
    assert d["status"] == "approved" and d["edited"] == 1 and "handig" in json.loads(d["steps_json"])[1]["body"]

    rows[0]["email_1"] = rows[0]["email_1"].split("Je zakelijke")[0]
    conn.execute("UPDATE drafts SET status='draft'")
    with open(tmp_path / "bad.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    c = l5_copy.import_review(cfg, conn, str(tmp_path / "bad.csv"))
    assert c["approved"] == 0 and "GDPR notice" in c["errors"][0]


class FlagFirstHook(StubJev):
    """Flags the first opening it is asked to fact-check, then passes the next one."""

    def __init__(self):
        super().__init__()
        self.checks = 0

    def post(self, url, json=None, timeout=None):
        if "unsupported_claim" in json["questions"]:
            self.checks += 1
            self.unsupported = 0.9 if self.checks == 1 else 0.05
        return super().post(url, json=json, timeout=timeout)


def test_flagged_opening_falls_back_to_a_safe_one(env):
    (env / "private").mkdir()
    (env / "private" / "sender.yaml").write_text("first_name: Sam\nfull_name: Sam Example\n")
    cfg = load_client(CLIENT)
    conn = db.connect()
    _setup(conn)
    l5_copy.draft(cfg, conn, jev=JevClient(cfg.ai, session=FlagFirstHook()))
    d = conn.execute("SELECT * FROM drafts").fetchone()
    assert d["status"] == "draft" and d["hook"] != "admin_job_ad" and d["qa_unsupported_p"] < 0.5
