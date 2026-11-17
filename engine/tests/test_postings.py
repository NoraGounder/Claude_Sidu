"""Job postings as Layer 1 evidence (BlitzAPI stub, synthetic data): stored per known account and
used as the Jev-confirmed job evidence's source URL."""

from test_l6_send import make_env

from gtm import db
from gtm.config import load_client
from gtm.crawl import Page, SiteCrawl
from gtm.layers import l1_hiring, l2_prefilter

CLIENT = "the-marble-jar"


class StubBlitz:
    records_remaining = 1000

    def __init__(self, postings):
        self.postings, self.calls = postings, []

    def jobs(self, job, company, max_results, cursor=None):
        self.calls.append((job, company, max_results))
        return {"results": self.postings, "cursor": None}


def test_postings_become_evidence_and_jev_sources(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch)
    cfg = load_client(CLIENT)
    conn = db.connect()
    cur = conn.execute("INSERT INTO accounts(client, name, linkedin_url, segments, source, status, first_seen, last_seen)"
                       " VALUES (?,?,?,?,?,?,?,?)", (CLIENT, "Groothandel BV",
                       "https://www.linkedin.com/company/groothandel-bv", '["wholesale_nl"]', "t", "tier_3", "t", "t"))
    acc = cur.lastrowid
    conn.commit()
    stub = StubBlitz([
        {"title": "Administratief medewerker", "url": "https://jobs.example/1", "date_posted": "2026-11-10",
         "company_linkedin_url": "https://www.linkedin.com/company/groothandel-bv/", "location": {"city": "Breda"}},
        {"title": "Order entry", "url": "https://jobs.example/2", "date_posted": "2026-11-12",
         "company_linkedin_url": "https://www.linkedin.com/company/unknown-co"}])
    r = l1_hiring.fetch_postings(cfg, conn, 50, client=stub)
    assert r == {"postings": 2, "accounts": 1, "account_ids": [acc]}
    assert stub.calls[0][1]["hq"]["country_code"]["include"] == ["BE", "NL"]
    assert l1_hiring.posted_jobs(conn, acc) == {"Administratief medewerker": "https://jobs.example/1"}
    # Twice is the same as once: the account's postings are replaced, not added.
    l1_hiring.fetch_postings(cfg, conn, 50, client=stub)
    assert len(l1_hiring.posted_jobs(conn, acc)) == 1

    site = SiteCrawl(home=Page(url="https://groothandel.example", status=200), posted=l1_hiring.posted_jobs(conn, acc))
    ev = l2_prefilter.jev_evidence(cfg, site, {"titles": {"Administratief medewerker": 0.95}})
    assert ev and ev[0].url == "https://jobs.example/1"
