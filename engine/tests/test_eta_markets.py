"""ETA search in the US (SBA PPP file) and Poland (KRS open API). Synthetic data only: every loan number,
company, KRS number, person and figure below is made up."""

import csv
from datetime import date

import pytest

from gtm.config import load_client
from gtm.crawl import Page
from gtm.eta import dol, markets, pl, qualify, store, us

TODAY = date(2026, 11, 21)
PPP_FIELDS = ["LoanNumber", "DateApproved", "ProcessingMethod", "BorrowerName", "BorrowerCity", "BorrowerState",
              "BorrowerZip", "LoanStatus", "CurrentApprovalAmount", "FranchiseName", "BusinessAgeDescription",
              "JobsReported", "NAICSCode", "BusinessType", "OriginatingLender", "NonProfit", "ForgivenessAmount",
              "Race", "Gender"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GTM_DATA_DIR", str(tmp_path))
    cfg = load_client("eta")
    return cfg, store.load_eta(cfg), store.connect(tmp_path / "engine.db"), tmp_path


def _loan(number, name, amount, jobs, naics="238220", method="PPP", age="Existing or more than 2 years old",
          btype="Subchapter S Corporation", zip_code="55401-1234", forgiven=None, franchise="", nonprofit=""):
    return {"LoanNumber": number, "DateApproved": "04/15/2020", "ProcessingMethod": method, "BorrowerName": name,
            "BorrowerCity": "Exampleton", "BorrowerState": "MN", "BorrowerZip": zip_code, "LoanStatus": "Paid in Full",
            "CurrentApprovalAmount": str(amount), "FranchiseName": franchise, "BusinessAgeDescription": age,
            "JobsReported": str(jobs), "NAICSCode": naics, "BusinessType": btype, "OriginatingLender": "Test Bank",
            "NonProfit": nonprofit, "ForgivenessAmount": str(forgiven if forgiven is not None else amount),
            "Race": "Unanswered", "Gender": "Unanswered"}


def _ppp(tmp_path, rows):
    path = tmp_path / "ppp.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PPP_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


# ---------- markets ----------

def test_market_from_id_and_industry_keys():
    assert markets.market_of("09999901") == "GB" and markets.market_of("US-123") == "US"
    assert markets.market_of("PL-0000099999") == "PL"
    assert markets.industry_key("US-1", "238220") == "naics:238220"
    assert markets.split_key("pkd:43.22.Z") == ("PL", "43.22.Z") and markets.split_key("71200") == ("GB", "71200")


# ---------- US ----------

def test_ppp_estimates_payroll_and_revenue_from_the_first_draw(env):
    _, eta, _, tmp = env
    # $500k first draw -> payroll $2.4M -> revenue $9.6M at the 25% construction payroll share
    rows = [_loan("9000000001", "EXAMPLE HEATING INC", 500000, 60),
            _loan("9000000002", "EXAMPLE HEATING, INC.", 450000, 58, method="PPS")]
    b = list(us.stream(_ppp(tmp, rows), eta["us"]))
    assert len(b) == 1                                   # both draws are one borrower
    b = b[0]
    assert b.company_id == "US-9000000001" and b.payroll_est == 2_400_000 and b.revenue_est == 9_600_000
    assert b.second_draw == 450000 and b.jobs == 60


def test_ppp_prefilter_drops_franchises_nonprofits_and_other_industries(env):
    _, eta, _, tmp = env
    rows = [_loan("9000000003", "FRANCHISE CLEAN LLC", 900000, 80, franchise="Big Brand"),
            _loan("9000000004", "COMMUNITY WORKS", 900000, 80, nonprofit="Y"),
            _loan("9000000005", "EXAMPLE DENTAL PC", 900000, 80, naics="621210"),
            _loan("9000000006", "TINY SHOP INC", 160000, 5)]
    assert list(us.stream(_ppp(tmp, rows), eta["us"])) == []


SF_FIELDS = ["ACK_ID", "SF_PLAN_EFF_DATE", "SF_SPONSOR_NAME", "SF_SPONSOR_DFE_DBA_NAME", "SF_SPONS_US_CITY",
             "SF_SPONS_US_STATE", "SF_SPONS_US_ZIP", "SF_SPONS_EIN", "SF_BUSINESS_CODE", "SF_TOT_ACT_PARTCP_EOY_CNT",
             "SF_FINAL_FILING_IND", "SF_SPONS_SIGNED_NAME", "SF_SPONS_PHONE_NUM", "SF_ADMIN_SIGNED_NAME",
             "SF_ADMIN_EIN", "SF_ADMIN_NAME_SAME_SPON_IND"]


def _sf(ein, name, active, since="1992-01-01", naics="238220", zip_code="55401", final="0", signer="PAT EXAMPLE",
        admin_signer="", admin_ein=""):
    return {"ACK_ID": "x", "SF_PLAN_EFF_DATE": since, "SF_SPONSOR_NAME": name, "SF_SPONSOR_DFE_DBA_NAME": "",
            "SF_SPONS_US_CITY": "EXAMPLETON", "SF_SPONS_US_STATE": "MN", "SF_SPONS_US_ZIP": zip_code,
            "SF_SPONS_EIN": ein, "SF_BUSINESS_CODE": naics, "SF_TOT_ACT_PARTCP_EOY_CNT": str(active),
            "SF_FINAL_FILING_IND": final, "SF_SPONS_SIGNED_NAME": signer, "SF_SPONS_PHONE_NUM": "",
            "SF_ADMIN_SIGNED_NAME": admin_signer, "SF_ADMIN_EIN": admin_ein, "SF_ADMIN_NAME_SAME_SPON_IND": ""}


def _write_sf(year, rows):
    path = dol.csv_path(year, "sf")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SF_FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_form5500_reads_headcount_plan_age_growth_and_final_filings(env):
    _write_sf(2021, [_sf("900000001", "STRONG MECHANICAL INC", 50)])
    _write_sf(2024, [_sf("900000001", "STRONG MECHANICAL INC", 64),
                     _sf("900000001", "STRONG MECHANICAL INC", 12, since="2015-01-01"),     # second plan
                     _sf("900000002", "CLOSED HEATING INC", 40, final="1"),
                     _sf("900000003", "DENTIST PC", 40, naics="621210")])
    emp = dol.employers([2021, 2024], {"238220"})
    assert set(emp) == {"900000001", "900000002"}
    e = emp["900000001"]
    assert (e.active, e.active_before, e.plan_since, e.plans) == (64, 50, 1992, 2)
    assert emp["900000002"].final_filing
    assert "signer" not in e.as_dict()


def test_us_sieve1_joins_form5500_and_ppp_and_keeps_no_fails(env):
    cfg, eta, conn, tmp = env
    _write_sf(2021, [_sf("900000010", "STRONG MECHANICAL INC", 60)])
    _write_sf(2024, [_sf("900000010", "STRONG MECHANICAL INC", 75),
                     _sf("900000011", "PLAN ONLY MECHANICAL INC", 70, since="2012-01-01"),
                     _sf("900000012", "ENDED MECHANICAL INC", 70, final="1")])
    ppp = _ppp(tmp, [_loan("9000000010", "STRONG MECHANICAL, INC.", 1_000_000, 70, zip_code="55401-0001"),
                     _loan("9000000013", "NO PLAN MECHANICAL INC", 1_000_000, 120),
                     _loan("9000000014", "NEW OWNER MECHANICAL INC", 1_000_000, 120, age="Change of Ownership")])
    emp = dol.employers([2021, 2024], {"238220"})
    out = us.run(conn, cfg.slug, eta, ppp, emp)
    assert out["both"] == 1 and out["fails"]["plan_ended_final_filing"] == 1
    assert out["fails"]["recent_change_of_ownership"] == 1
    kept = {r["company_number"]: r for r in conn.execute("SELECT * FROM eta_screen WHERE sieve=1")}
    assert {"US-900000010", "US-9000000013"} <= set(kept)                  # EIN id for filers, loan id otherwise
    assert kept["US-900000010"]["score"] > kept["US-9000000013"]["score"]  # current, growing, both sources
    import json
    m = json.loads(kept["US-900000010"]["metrics"])
    assert m["headcount"] == 75 and m["headcount_source"] == "form5500 2024" and m["sources"] == ["form5500", "ppp"]
    typical = 75 * 230_000
    assert typical * 0.6 <= m["revenue_est"] <= typical * 1.6                 # clamped around the industry norm
    ledger = {r["claim"]: r for r in store.evidence(conn, cfg.slug, "US-900000010")}
    assert ledger["Active plan participants (2024)"]["value"] == "75"
    assert ledger["Revenue (estimate)"]["status"] == "unverified"
    assert ledger["Owner age"]["status"] == "unknown"
    assert store.owners(conn, cfg.slug, "US-900000010")[0]["name"] == "PAT EXAMPLE"
    assert "Race" not in str(list(conn.execute("SELECT metrics FROM eta_screen")))


def test_us_website_needs_name_and_zip():
    row = {"company_number": "US-1", "name": "STRONG MECHANICAL INC", "postal_code": "55401",
           "locality": "Exampleton, MN"}
    assert qualify.belongs("Strong Mechanical - 12 Main St, Exampleton, MN 55401", row)
    assert not qualify.belongs("Strong Mechanical of Texas, Dallas TX 75201", row)
    assert qualify.domain_candidates("STRONG MECHANICAL INC", "US")[0] == "strongmechanical.com"


# ---------- Poland ----------

def _odpis(krs="0000099999", form="SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ", pkd=("43", "22", "Z"),
           registered="05.06.2001", filed=("12.06.2026", "15.06.2025", "20.06.2024"), corporate_owner=False,
           troubled=False, pesel="55031512345"):
    holders = [{"nazwisko": {"nazwiskoICzlon": "PRZYKŁADOWY"}, "imiona": {"imie": "JAN"},
                "identyfikator": {"pesel": pesel}, "posiadaneUdzialy": "80 UDZIAŁÓW O ŁĄCZNEJ WARTOŚCI 40 000 ZŁ",
                "czyPosiadaCaloscUdzialow": False}]
    holders.append({"nazwa": "PRZYKŁAD HOLDING SP. Z O.O.", "identyfikator": {"krs": "0000088888"},
                    "posiadaneUdzialy": ("920" if corporate_owner else "20") + " UDZIAŁÓW",
                    "czyPosiadaCaloscUdzialow": False})
    return {"naglowekA": {"numerKRS": krs, "dataRejestracjiWKRS": registered},
            "dane": {"dzial1": {"danePodmiotu": {"nazwa": "PRZYKŁAD INSTALACJE SP. Z O.O.", "formaPrawna": form,
                                                 "identyfikatory": {"nip": "0000000000", "regon": "000000000"}},
                                "siedzibaIAdres": {"siedziba": {"miejscowosc": "PRZYKŁADOWO", "wojewodztwo": "MAZOWIECKIE"}},
                                "kapital": {"wysokoscKapitaluZakladowego": {"wartosc": "50000,00", "waluta": "PLN"}},
                                "wspolnicySpzoo": holders},
                     "dzial2": {"reprezentacja": {"nazwaOrganu": "ZARZĄD", "sklad": [
                         {"nazwisko": {"nazwiskoICzlon": "PRZYKŁADOWY"}, "imiona": {"imie": "JAN"},
                          "identyfikator": {"pesel": pesel}, "funkcjaWOrganie": "PREZES ZARZĄDU"}]}},
                     "dzial3": {"przedmiotDzialalnosci": {
                         "przedmiotPrzewazajacejDzialalnosci": [{"opis": "TEST", "kodDzial": pkd[0], "kodKlasa": pkd[1],
                                                                 "kodPodklasa": pkd[2]}]},
                         "wzmiankiOZlozonychDokumentach": {"wzmiankaOZlozeniuRocznegoSprawozdaniaFinansowego": [
                             {"dataZlozenia": f, "zaOkresOdDo": f"01.01.{int(f[-4:]) - 1} - 31.12.{int(f[-4:]) - 1}"}
                             for f in filed]}},
                     "dzial6": {"likwidacja": {"likwidatorzy": []}} if not troubled else
                               {"postepowanieUpadlosciowe": {"data": "01.02.2026"}}}}


def test_krs_extract_parses_identity_codes_owners_and_filings():
    p = pl.parse(_odpis())
    assert p["krs"] == "0000099999" and p["registered"] == "2001-06-05" and p["pkd_main"] == ["43.22.Z"]
    assert p["capital_pln"] == 50000 and p["filed_accounts"][0] == {"filed": "2026-06-12", "period_end": "2025-12-31"}
    jan = p["shareholders"][0]
    assert jan["name"] == "JAN PRZYKŁADOWY" and jan["shares"] == 80 and (jan["birth_year"], jan["birth_month"]) == (1955, 3)
    assert p["shareholders"][1]["corporate"] and not p["troubled"]
    assert "pesel" not in str(p).lower() and "55031512345" not in str(p)    # never kept


def test_pesel_birth_handles_centuries_and_masks():
    assert pl.pesel_birth("02270812345") == (2002, 7)
    assert pl.pesel_birth("55*********") == (None, None)


def test_pl_sieve1_caps_at_review_without_numbers_and_fails_group_owned():
    sieve = load_client("eta") and store.load_eta(load_client("eta"))["pl"]["sieve1"]
    verdict, score, fails, _ = pl.evaluate(pl.parse(_odpis()), sieve, TODAY)
    assert verdict == "review" and score >= sieve["pass"] and not fails     # would pass; size unknown
    assert "no_motivated_owner_group_owned" in pl.evaluate(pl.parse(_odpis(corporate_owner=True)), sieve, TODAY)[2]
    assert "liquidation_bankruptcy_or_restructuring" in pl.evaluate(pl.parse(_odpis(troubled=True)), sieve, TODAY)[2]
    assert "accounts_not_filed_recently" in pl.evaluate(pl.parse(_odpis(filed=("10.06.2023",))), sieve, TODAY)[2]


class FakeKRS:
    def __init__(self, extracts, bulletin):
        self.extracts, self.days, self.requests_made, self.calls = extracts, bulletin, 0, []

    def bulletin(self, day):
        self.requests_made += 1
        return self.days.get(day, [])

    def extract(self, krs):
        self.requests_made += 1
        self.calls.append(krs)
        return self.extracts.get(krs)


def test_pl_discovery_keeps_target_pkd_and_never_rereads_a_number(env):
    cfg, eta, conn, _ = env
    krs = FakeKRS({"0000099999": _odpis(), "0000077777": _odpis("0000077777", pkd=("47", "11", "Z")),
                   "0000066666": _odpis("0000066666", form="SPÓŁKA JAWNA")},
                  {"2026-11-20": ["0000099999", "0000099999", "0000077777", "0000066666", "0000055555"]})
    out = pl.run(conn, cfg.slug, eta, krs, ["2026-11-20"], today=TODAY)
    assert out["kept"] == 1 and out["review"] == 1
    assert out["skipped"] == {"pkd": 1, "legal_form": 1, "not_in_register_p": 1}
    row = conn.execute("SELECT * FROM eta_companies WHERE company_number='PL-0000099999'").fetchone()
    assert row["search_code"] == "43.22.Z" and row["stage"] == "screened"
    assert len(store.owners(conn, cfg.slug, "PL-0000099999")) == 3
    pl.run(conn, cfg.slug, eta, krs, ["2026-11-20"], today=TODAY)
    assert len(krs.calls) == 4                                              # second run fetched nothing


def test_pl_maintenance_page_stops_cleanly(env):
    cfg, eta, conn, _ = env

    class Down(FakeKRS):
        def bulletin(self, day):
            raise pl.KRSUnavailable("KRS API Biuletyn -> 200 (maintenance page)")

    out = pl.run(conn, cfg.slug, eta, Down({}, {}), ["2026-11-20"])
    assert "maintenance" in out["stopped"] and out["read"] == 0


def test_polish_site_is_verified_by_krs_number():
    row = {"company_number": "PL-0000099999", "name": "PRZYKŁAD INSTALACJE SP. Z O.O.", "postal_code": None,
           "locality": "PRZYKŁADOWO"}
    assert qualify.belongs("Sąd Rejonowy, KRS 0000099999, NIP 000-000-00-00", row)
    assert not qualify.belongs("KRS 0000099998", row)
    assert qualify.domain_candidates("PRZYKŁAD INSTALACJE SP. Z O.O.", "PL")[0].endswith(".pl")


# ---------- US owner lookup ----------

from gtm.eta import owners_us
from gtm.sources.fullenrich import SearchResult


def _person(title, edu_start=None, first_job=None, since=None, domain="strongmechanical.com"):
    jobs = [{"title": "Apprentice", "start_at": f"{first_job}-06-01T00:00:00Z", "is_current": False,
             "company": {"domain": "other.com"}}] if first_job else []
    jobs.append({"title": title, "start_at": f"{since}-01-01T00:00:00Z" if since else None, "is_current": True,
                 "company": {"domain": domain}})
    return {"id": f"p-{title}", "full_name": f"Test {title}", "educations":
            [{"start_at": f"{edu_start}-09-01T00:00:00Z", "end_at": f"{edu_start + 4}-06-01T00:00:00Z"}] if edu_start else [],
            "employment": {"current": {"title": title, "start_at": f"{since}-01-01T00:00:00Z" if since else None},
                           "all": jobs}}


def test_owner_age_from_degree_or_first_job():
    today = date(2026, 11, 23)
    e = owners_us.estimate(_person("Owner", edu_start=1978, since=1990), "strongmechanical.com", today)
    assert (e.age, e.floor, e.tenure_since) == (66, False, 1990)            # 1978 - 18 = born 1960
    e = owners_us.estimate(_person("President", first_job=1985), "strongmechanical.com", today)
    assert (e.age, e.floor) == (63, True)                                    # at least 63
    assert owners_us.estimate(_person("CEO"), "x.com", today).age is None


class FakeFE:
    def __init__(self, people):
        self.people, self.calls = people, []

    def search_people(self, domain, titles, limit=4):
        self.calls.append((domain, titles, limit))
        return SearchResult(people=self.people[:limit], credits=0.25 * min(limit, len(self.people)),
                            total=len(self.people))


def _shortlisted(conn, client, number="US-900000010", website="https://www.strongmechanical.com/"):
    store.upsert_company(conn, client, {"company_number": number, "name": "STRONG MECHANICAL INC",
                                        "stage": "screened", "source": "form5500"})
    store.save_screen(conn, client, number, 1, "pass", 90, [], {}, {})
    store.save_screen(conn, client, number, 2, "watch", 70, [], {}, {})
    qualify.ensure_schema(conn)
    conn.execute("INSERT INTO eta_websites(client, company_number, website, tried, checked_at) VALUES (?,?,?,?,?)",
                 (client, number, website, "[]", "2026-11-23"))
    conn.commit()


def test_owner_lookup_dry_run_spends_nothing_and_zero_cap_blocks_live(env, capsys, monkeypatch):
    cfg, eta, conn, _ = env
    _shortlisted(conn, cfg.slug)
    from gtm.eta import cli as eta_cli
    from types import SimpleNamespace
    monkeypatch.setattr(eta_cli, "_setup", lambda a: (cfg, eta, conn))
    cfg.limits.month_budget_usd["fullenrich"] = 0             # no cap set: a live run must be refused
    fe = FakeFE([_person("Owner", edu_start=1978, since=1990)])
    eta_cli.cmd_owners(SimpleNamespace(client="eta", limit=None, per_company=3, dry_run=True), fe=fe)
    out = capsys.readouterr().out
    assert "1 companies" in out and "strongmechanical.com" in out and fe.calls == []
    with pytest.raises(Exception, match="budget"):
        eta_cli.cmd_owners(SimpleNamespace(client="eta", limit=None, per_company=3, dry_run=False), fe=fe)
    assert fe.calls == []


def test_owner_lookup_saves_likely_owner_first_and_marks_estimates(env):
    cfg, eta, conn, _ = env
    _shortlisted(conn, cfg.slug)
    cfg.limits.month_budget_usd["fullenrich"] = 1.0          # a test cap; the real one is Sidarth's to set
    fe = FakeFE([_person("Vice President Operations", edu_start=1995), _person("Owner", edu_start=1978, since=1990)])
    out = owners_us.run(conn, cfg, fe, per_company=3, today=date(2026, 11, 23))
    assert out["companies"] == 1 and out["people"] == 2 and fe.calls[0][0] == "strongmechanical.com"
    ledger = {r["claim"]: r for r in store.evidence(conn, cfg.slug, "US-900000010")}
    assert ledger["Owner age (estimate)"]["value"] == "about 66 (Owner)"
    assert ledger["Owner or CEO found"]["value"] == "Owner"
    assert ledger["Owner age (estimate)"]["status"] == "unverified" and ledger["Leader since"]["value"] == "1990"
    assert owners_us.targets(conn, cfg.slug) == []                          # never looked up twice
    run = conn.execute("SELECT * FROM runs WHERE vendor='fullenrich' ORDER BY id DESC").fetchone()
    assert run["actual_cost"] == round(0.5 * 0.055, 4)


def test_vice_presidents_are_never_the_owner():
    assert owners_us.title_rank("Vice President of Finance") == 9
    assert owners_us.title_rank("Executive Vice President") == 9
    assert owners_us.title_rank("President and CEO") == 1
    assert owners_us.title_rank("Owner / President") == 0
    assert owners_us.title_rank("Managing Principal") == 2


def test_no_leader_found_means_owner_age_unknown(env):
    cfg, eta, conn, _ = env
    _shortlisted(conn, cfg.slug)
    cfg.limits.month_budget_usd["fullenrich"] = 1.0
    owners_us.run(conn, cfg, FakeFE([_person("Vice President Operations", edu_start=1970)]), today=date(2026, 11, 23))
    ledger = {r["claim"]: r for r in store.evidence(conn, cfg.slug, "US-900000010")}
    assert ledger["Owner age (estimate)"]["status"] == "unknown" and ledger["Owner or CEO found"]["value"] == "no"


def test_admin_signer_counts_only_when_the_administrator_is_the_employer(env):
    _write_sf(2024, [_sf("900000020", "SELF RUN HEATING INC", 60, signer="", admin_signer="LEE OWNER"),
                     _sf("900000021", "TPA RUN HEATING INC", 60, signer="", admin_signer="TPA CLERK",
                         admin_ein="800000000")])
    emp = dol.employers([2024], {"238220"})
    assert emp["900000020"].signer == "LEE OWNER" and emp["900000021"].signer is None


def test_us_rebuild_keeps_sieve2_and_paid_owner_lookups(env):
    cfg, eta, conn, tmp = env
    _write_sf(2024, [_sf("900000010", "STRONG MECHANICAL INC", 75)])
    emp = dol.employers([2024], {"238220"})
    us.run(conn, cfg.slug, eta, None, emp)
    cid = "US-900000010"
    store.save_screen(conn, cfg.slug, cid, 2, "qualified", 80, [], {}, {})
    store.save_owner(conn, cfg.slug, cid, {"person_key": "fullenrich:p1", "kind": "director", "name": "Test Owner",
                                            "role": "Owner", "birth_year": 1960, "birth_month": None,
                                            "appointed_on": "1990", "ceased_on": None, "ownership": None,
                                            "source": "fullenrich people search (x.com); age: test"})
    store.record_evidence(conn, cfg.slug, cid, "Owner age (estimate)", "about 66 (Owner)", "unverified", "FullEnrich")
    us.clear_rebuildable(conn, cfg.slug)
    us.run(conn, cfg.slug, eta, None, emp)
    names = {o["name"] for o in store.owners(conn, cfg.slug, cid)}
    assert names == {"Test Owner", "PAT EXAMPLE"}
    ledger = {r["claim"]: r for r in store.evidence(conn, cfg.slug, cid)}
    assert ledger["Owner age (estimate)"]["value"] == "about 66 (Owner)" and "Active plan participants (2024)" in ledger
    assert conn.execute("SELECT verdict FROM eta_screen WHERE company_number=? AND sieve=2", (cid,)).fetchone()[0] == "qualified"


# ---------- decisions and outreach prep ----------

from gtm.eta import outreach


class FakeEnrich(FakeFE):
    def start_enrichment(self, name, contacts):
        self.calls.append(("enrich", contacts))
        return "e1"

    def wait_enrichment(self, eid):
        return {"cost": {"credits": 1}, "data": [{"contact_info": {"most_probable_work_email": {
            "email": "owner@strongmechanical.com", "status": "DELIVERABLE"}}}]}


def test_yes_prepares_contact_and_drafts_but_sends_nothing(env):
    cfg, eta, conn, tmp = env
    _write_sf(2024, [_sf("900000010", "STRONG MECHANICAL INC", 75)])
    us.run(conn, cfg.slug, eta, None, dol.employers([2024], {"238220"}))
    _shortlisted(conn, cfg.slug)
    cfg.limits.month_budget_usd["fullenrich"] = 1.0
    owners_us.run(conn, cfg, FakeFE([_person("Owner", edu_start=1978, since=1990)]), today=date(2026, 11, 23))
    outreach.decide(conn, cfg.slug, "US-900000010", "yes")
    fe = FakeEnrich([])
    r = outreach.prepare(conn, cfg, eta, fe, today=date(2026, 11, 23))
    assert r["companies"] == 1 and r["emails"] == 1 and r["addresses"] == 1
    text = open(r["files"][0]).read()
    assert "draft, not sent" in text and "owner@strongmechanical.com" in text and "Dear Test," in text
    assert "{{YOUR FULL NAME}}" in text and "reply \"no\"" in text
    outreach.prepare(conn, cfg, eta, fe, today=date(2026, 11, 23))
    assert len([c for c in fe.calls if c[0] == "enrich"]) == 1                # never looked up twice


# ---------- outreach through Smartlead ----------

import shutil

from gtm.eta import send


class FakeSmartlead:
    def __init__(self, accounts):
        self.accounts, self.calls = accounts, []

    def email_accounts(self):
        return self.accounts

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args))
            return 77 if name == "create_campaign" else {}
        return call


def _mailbox(i, email, days, rep="100%"):
    from datetime import datetime, timedelta
    return {"id": i, "from_email": email, "created_at": (datetime.utcnow() - timedelta(days=days)).isoformat(),
            "message_per_day": 15, "warmup_details": {"status": "ACTIVE", "warmup_reputation": rep}}


def test_short_name_and_fill():
    assert outreach.short_name("MEYER & DEPEW COMPANY, INC.") == "Meyer & Depew"
    assert outreach.short_name("DEE CRAMER, INC.") == "Dee Cramer"
    text = "{{ONE SENTENCE ABOUT YOUR BACKGROUND, e.g. x}} {{HOW THE PURCHASE WOULD BE FUNDED, e.g. y}}\n" \
           "{{PHONE}} | {{EMAIL}}\n{{POSTAL ADDRESS (US law)}}"
    out = send.fill(text, {"background": "B.", "funding": "F.", "phone": "1", "postal_address": "A"}, "Note.")
    assert out == "B. F.\n\nNote.\n1\nA" and "{{" not in out


def test_eta_send_holds_until_details_then_uploads_paused_to_own_domain_only(env):
    cfg, eta, conn, tmp = env
    root = tmp / "clients" / "eta"
    shutil.copytree(cfg.root, root, ignore=shutil.ignore_patterns("private"))
    cfg = cfg.model_copy(update={"root": root})
    _write_sf(2024, [_sf("900000010", "STRONG MECHANICAL INC", 75)])
    us.run(conn, cfg.slug, eta, None, dol.employers([2024], {"238220"}))
    _shortlisted(conn, cfg.slug)
    cfg.limits.month_budget_usd["fullenrich"] = 1.0
    owners_us.run(conn, cfg, FakeFE([_person("Owner", edu_start=1978, since=1990)]), today=date(2026, 11, 23))
    outreach.decide(conn, cfg.slug, "US-900000010", "yes")
    outreach.prepare(conn, cfg, eta, FakeEnrich([]), today=date(2026, 11, 23))

    p = send.plan(conn, cfg)                                   # no sender file yet: nothing is ready
    assert not p["ready"] and p["held"][0][1] == "your details are not filled in yet"

    (root / "private").mkdir()
    (root / "private" / "sender.yaml").write_text(
        "full_name: Pat Buyer\nbackground: I ran operations.\nfunding: Own capital.\nphone: '555'\n"
        "postal_address: 1 Main St\n")
    p = send.plan(conn, cfg)
    assert len(p["ready"]) == 1
    body = p["ready"][0]["steps"][0]
    assert "{{" not in body and "Pat Buyer" in body and "Quailworks address" in body and "1 Main St" in body
    assert p["ready"][0]["subject"] == "Strong Mechanical: a question about the long term"

    sl = FakeSmartlead([_mailbox(1, "a@quailworkshq.com", 16), _mailbox(2, "b@getquailworks.com", 30),
                        _mailbox(3, "c@quailworkshq.com", 3)])
    r = send.push(conn, cfg, sl)
    assert r["pushed"] == 1 and r["mailboxes"] == 1
    names = [c[0] for c in sl.calls]
    assert "set_status" not in names                           # uploaded paused, never started
    assert ("link_email_accounts", (77, [1])) in sl.calls      # own warm domain only
    assert send.push(conn, cfg, sl)["pushed"] == 0              # never uploaded twice


# ---------- partners: capital, brokers, advisers ----------

from types import SimpleNamespace

from gtm.eta import partners


class FakeBlitzPartners:
    def __init__(self):
        self.calls = []

    def search_companies(self, company, max_results, cursor=None):
        self.calls.append(("companies", company))
        return {"results": [{"name": "Oak Family Office", "domain": "oakfo.example", "linkedin_url": "https://li/oak",
                             "industry": "Venture Capital and Private Equity Principals", "size": "1-10",
                             "hq": {"country_code": "US", "city": "Austin"}},
                            {"name": "Thin Site LLC", "domain": "thin.example", "hq": {"country_code": "US"}}][:max_results],
                "cursor": None}

    def people(self, url, cascade, max_results=4):
        self.calls.append(("people", url, cascade))
        return [{"person": {"full_name": "Pat Partner", "linkedin_url": "https://li/pat",
                            "experiences": [{"job_is_current": True, "job_title": "Managing Partner"}]}}]


class FakeSiteFetcher:
    def get(self, url):
        text = "We back independent sponsors buying lower middle market companies. " * 20 if "oak" in url else "hi"
        return SimpleNamespace(ok=True, text=text, title="Oak" if "oak" in url else "Thin", links=[])


class FakeJevPartners:
    def decide(self, state, questions):
        assert set(questions) == {"fit", "check"}
        return SimpleNamespace(answers={"fit": {"score": 1.8}, "check": {"noul": 0.9}}, model_id="typesafe/jev-1.14",
                               input_tokens=10, output_tokens=5, cost_usd=0.0001, latency_ms=5, request_id="r1")


def test_partners_search_check_people_export(env):
    cfg, eta, conn, tmp = env
    conf = partners.load(cfg.root)
    conf["kinds"] = {"capital": dict(conf["kinds"]["capital"], searches=[{"name": "fo", "keywords": ["family office"],
                                                                          "max_items": 2}])}
    api = FakeBlitzPartners()
    r = partners.search(conn, cfg, conf, api)
    assert r["new"] == 2 and partners.records_used(conn, cfg.slug) == 2
    assert partners.search(conn, cfg, conf, api)["new"] == 0                     # seen firms are not added twice
    c = partners.check(conn, cfg, conf, FakeSiteFetcher(), FakeJevPartners())
    assert c["fit"] == 1 and c["no_site"] == 1                                   # a thin site is never sent to Jev
    p = partners.people(conn, cfg, conf, api)
    assert p["people"] == 1 and api.calls[-1][2][0]["include_title"] == ["Managing Partner"]
    out = partners.export(conn, cfg, conf)
    assert out["counts"]["capital"]["strong"] == 1
    text = (tmp / "eta" / "partners" / "capital.csv").read_text()
    assert "Oak Family Office" in text and "Pat Partner (Managing Partner)" in text and "Thin Site" not in text


def test_partners_respect_the_record_cap(env):
    cfg, eta, conn, tmp = env
    conf = partners.load(cfg.root)
    cfg.limits.month_budget_usd["blitzapi_records"] = 10
    with pytest.raises(Exception, match="records"):
        partners.search(conn, cfg, conf, FakeBlitzPartners())


def test_long_company_names_never_crash_the_website_search():
    from gtm.crawl import Fetcher
    long = "the very long and winding name of a company that keeps going on and on incorporated"
    assert all(len(c.split(".")[0]) <= 63 for c in qualify.domain_candidates(long, "US"))
    page = Fetcher(use_cache=False).get("https://" + "a" * 70 + ".com/")
    assert not page.ok                                         # an unreadable site, not an exception
