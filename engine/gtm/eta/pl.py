"""Poland: discovery and sieve 1 from the KRS open API (Ministry of Justice, free, no key).

    GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json   current extract
    GET https://api-krs.ms.gov.pl/api/krs/Biuletyn/{YYYY-MM-DD}                       KRS numbers with an entry that day

The API cannot search by industry, so discovery reads the daily bulletin (every company with a register entry
that day; filing annual accounts is such an entry, so the filing season covers nearly every active company),
fetches each new number's extract once, and keeps the companies whose main PKD code and legal form are in
eta.yaml. Numbers already read are remembered (eta_pl_seen) and never fetched again.

The extract gives identity, registration date, PKD codes, shareholders, board, filed annual accounts and any
liquidation or bankruptcy. It has no numbers: filed statements sit in the RDF repository, which is behind bot
protection and is not crawled. Without numbers no Polish company passes sieve 1 (size_unknown_verdict).

Personal data: names and roles stay in data/engine.db (gitignored), like the UK owners. A PESEL is never stored;
when the extract shows a full one, only the birth year and month are kept (they are encoded in it).
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta

import requests

from gtm import db
from gtm.eta import store

SOURCE = "krs:open_api"
REGISTER = "https://wyszukiwarka-krs.ms.gov.pl"


class KRSUnavailable(RuntimeError):
    """The API answered with its maintenance page (Przerwa techniczna) or a server error."""


class KRSClient:
    def __init__(self, api: str = "https://api-krs.ms.gov.pl/api/krs", per_second: float = 2.0,
                 session=None, sleep=time.sleep, max_requests: int | None = None):
        self.api, self.gap = api.rstrip("/"), 1.0 / per_second if per_second else 0
        self.http = session or requests.Session()
        self.http.headers.update({"Accept": "application/json", "User-Agent": "eta-search/0.1"})
        self._sleep, self.max_requests, self.requests_made = sleep, max_requests, 0

    def _get(self, path: str):
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise KRSUnavailable(f"request cap of {self.max_requests} reached")
        if self.requests_made and self.gap:
            self._sleep(self.gap)
        self.requests_made += 1
        resp = self.http.get(f"{self.api}{path}", timeout=60)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 500 or "json" not in resp.headers.get("content-type", ""):
            raise KRSUnavailable(f"KRS API {path.split('/')[1]} -> {resp.status_code} "
                                 f"({'maintenance page' if 'Przerwa' in resp.text[:500] else resp.text[:120]!r})")
        if resp.status_code >= 400:
            raise KRSUnavailable(f"KRS API {path} -> {resp.status_code}")
        return resp.json()

    def extract(self, krs: str) -> dict | None:
        data = self._get(f"/OdpisAktualny/{str(krs).zfill(10)}?rejestr=P&format=json")
        return (data or {}).get("odpis") if data else None

    def bulletin(self, day: str) -> list[str]:
        return [str(n).zfill(10) for n in (self._get(f"/Biuletyn/{day}") or [])]


# ---------- parsing the extract ----------

def _d(text: str | None) -> str | None:
    """'05.06.2001' -> '2001-06-05'."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", (text or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def _name(person: dict) -> str:
    if person.get("nazwa"):
        return str(person["nazwa"])
    surname = person.get("nazwisko") or ""
    first = person.get("imiona") or ""
    if isinstance(surname, dict):
        surname = surname.get("nazwiskoICzlon") or surname.get("nazwisko") or ""
    if isinstance(first, dict):
        first = " ".join(x for x in (first.get("imie"), first.get("imieDrugie")) if x)
    return " ".join(x for x in (str(first), str(surname)) if x).strip()


def _filled(value) -> bool:
    """True when a section holds at least one real value (empty dicts and lists are only scaffolding)."""
    if isinstance(value, dict):
        return any(_filled(v) for v in value.values())
    if isinstance(value, list):
        return any(_filled(v) for v in value)
    return value not in (None, "", False)


def pesel_birth(pesel: str | None) -> tuple[int | None, int | None]:
    """Birth year and month from a full PESEL (11 digits); None for masked or missing ones."""
    if not pesel or not re.fullmatch(r"\d{11}", pesel):
        return None, None
    yy, mm = int(pesel[:2]), int(pesel[2:4])
    for offset, century in ((80, 1800), (0, 1900), (20, 2000), (40, 2100), (60, 2200)):
        if offset < mm <= offset + 12:
            return century + yy, mm - offset
    return None, None


_SHARES = re.compile(r"(\d[\d\s]*)\s*UDZIA", re.I)


def _share_count(text: str | None) -> int | None:
    m = _SHARES.search(text or "")
    return int(re.sub(r"\s", "", m.group(1))) if m else None


def parse(odpis: dict) -> dict:
    head = odpis.get("naglowekA") or {}
    dane = odpis.get("dane") or {}
    d1, d2, d3, d6 = (dane.get(k) or {} for k in ("dzial1", "dzial2", "dzial3", "dzial6"))
    firm = d1.get("danePodmiotu") or {}
    ids = firm.get("identyfikatory") or {}
    seat = (d1.get("siedzibaIAdres") or {})
    city = ((seat.get("siedziba") or {}).get("miejscowosc") or (seat.get("adres") or {}).get("miejscowosc"))
    capital = ((d1.get("kapital") or {}).get("wysokoscKapitaluZakladowego") or {}).get("wartosc")
    try:
        capital = float(str(capital).replace(" ", "").replace(",", ".")) if capital is not None else None
    except ValueError:
        capital = None

    activity = d3.get("przedmiotDzialalnosci") or {}
    def codes(key):
        return [f"{c.get('kodDzial')}.{c.get('kodKlasa')}.{c.get('kodPodklasa')}"
                for c in _list(activity.get(key)) if c.get("kodDzial")]

    shareholders = []
    for s in _list(d1.get("wspolnicySpzoo")):
        ident = s.get("identyfikator") or {}
        year, month = pesel_birth(ident.get("pesel"))
        shareholders.append({"name": _name(s), "corporate": bool(s.get("nazwa") or ident.get("krs") or
                                                                 (ident.get("regon") and not ident.get("pesel"))),
                             "shares": _share_count(s.get("posiadaneUdzialy")),
                             "whole": bool(s.get("czyPosiadaCaloscUdzialow")),
                             "birth_year": year, "birth_month": month})
    board = []
    for organ in _list(d2.get("reprezentacja")):
        for m in _list(organ.get("sklad")):
            year, month = pesel_birth((m.get("identyfikator") or {}).get("pesel"))
            board.append({"name": _name(m), "role": m.get("funkcjaWOrganie") or organ.get("nazwaOrganu"),
                          "birth_year": year, "birth_month": month})
    filed = []
    docs = d3.get("wzmiankiOZlozonychDokumentach") or {}
    for w in _list(docs.get("wzmiankaOZlozeniuRocznegoSprawozdaniaFinansowego")):
        period = re.findall(r"\d{2}\.\d{2}\.\d{4}", w.get("zaOkresOdDo") or "")
        filed.append({"filed": _d(w.get("dataZlozenia")), "period_end": _d(period[-1]) if period else None})
    filed.sort(key=lambda f: f["filed"] or "", reverse=True)
    troubled = any(_filled(v) for k, v in d6.items() if re.search(r"likwid|upad|restruktur|zawiesz", k, re.I))

    return {"krs": str(head.get("numerKRS") or "").zfill(10), "name": firm.get("nazwa"),
            "legal_form": firm.get("formaPrawna"), "nip": ids.get("nip"), "regon": ids.get("regon"),
            "registered": _d(head.get("dataRejestracjiWKRS")), "city": city,
            "voivodeship": (seat.get("siedziba") or {}).get("wojewodztwo"), "capital_pln": capital,
            "pkd_main": codes("przedmiotPrzewazajacejDzialalnosci"), "pkd_other": codes("przedmiotPozostalejDzialalnosci"),
            "shareholders": shareholders, "board": board, "filed_accounts": filed, "troubled": troubled}


# ---------- sieve 1 ----------

def _years(day: str | None, today: date) -> float | None:
    if not day:
        return None
    y, m, d = (int(x) for x in day.split("-"))
    return round((today - date(y, m, d)).days / 365.25, 1)


def corporate_majority(p: dict) -> bool:
    holders = p["shareholders"]
    if not holders:
        return False
    if any(h["corporate"] and h["whole"] for h in holders):
        return True
    total = sum(h["shares"] or 0 for h in holders)
    corp = sum(h["shares"] or 0 for h in holders if h["corporate"])
    return bool(total) and corp / total > 0.5


def owner_age(p: dict, today: date) -> int | None:
    years = [x["birth_year"] for x in p["shareholders"] + p["board"] if x.get("birth_year")]
    return today.year - min(years) if years else None


def owner_operated(p: dict) -> bool:
    board = {b["name"].lower() for b in p["board"] if b["name"]}
    return any(not h["corporate"] and h["name"].lower() in board for h in p["shareholders"])


def evaluate(p: dict, sieve: dict, today: date | None = None) -> tuple[str, float, list[str], dict]:
    today = today or date.today()
    hard, bars, weights = sieve.get("hard") or {}, sieve.get("bars") or {}, sieve.get("weights") or {}
    years = _years(p["registered"], today)
    last = p["filed_accounts"][0]["filed"] if p["filed_accounts"] else None
    months = None if not last else round(_years(last, today) * 12, 1)
    fails = []
    if years is not None and years < hard.get("min_years_in_krs", 10):
        fails.append("short_history")
    if hard.get("exclude_liquidation_or_bankruptcy", True) and p["troubled"]:
        fails.append("liquidation_bankruptcy_or_restructuring")
    if months is None or months > hard.get("max_months_since_accounts_filed", 20):
        fails.append("accounts_not_filed_recently")
    if hard.get("exclude_corporate_majority_owner", True) and corporate_majority(p):
        fails.append("no_motivated_owner_group_owned")
    age = owner_age(p, today)
    recent = {f["filed"][:4] for f in p["filed_accounts"] if f["filed"]}
    want = {str(today.year - i) for i in range(0, 4)}
    parts = {
        "history": min((years or 0) / 20, 1.0),
        "filings": min(len(recent & want) / 3, 1.0),
        "motivated_seller": (1.0 if age and age >= bars.get("owner_age_motivated", 60)
                             else 0.6 if age and age >= bars.get("owner_age_watch", 55) else 0.3 if age is None else 0.1),
        "owner_operated": 1.0 if owner_operated(p) else 0.3,
        "capital": 1.0 if (p["capital_pln"] or 0) >= 50000 else 0.5,
    }
    breakdown = {k: round(v * float(weights.get(k, 0)), 1) for k, v in parts.items()}
    score = round(sum(breakdown.values()), 1)
    if fails:
        return "fail", score, fails, breakdown
    verdict = "pass" if score >= sieve.get("pass", 60) else "review" if score >= sieve.get("review", 40) else "fail"
    if verdict == "pass" and sieve.get("size_unknown_verdict"):
        verdict = sieve["size_unknown_verdict"]       # no filed numbers read: size unknown
    return verdict, score, fails, breakdown


# ---------- discovery ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_pl_seen (
    client      TEXT NOT NULL,
    krs         TEXT NOT NULL,
    kept        INTEGER NOT NULL,
    reason      TEXT,
    checked_at  TEXT NOT NULL,
    PRIMARY KEY (client, krs)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def keep_reason(p: dict, pl: dict) -> str | None:
    forms = {f.upper() for f in pl.get("legal_forms") or []}
    if forms and (p["legal_form"] or "").upper() not in forms:
        return "legal_form"
    codes = {str(c) for c in (pl.get("pkd_codes") or {})}
    if codes and not set(p["pkd_main"]) & codes:
        return "pkd"
    return None


def save(conn, client: str, p: dict, pl: dict, today: date | None = None) -> str:
    cid = f"PL-{p['krs']}"
    code = next((c for c in p["pkd_main"] if c in {str(k) for k in pl.get("pkd_codes") or {}}), None)
    store.upsert_company(conn, client, {
        "company_number": cid, "name": p["name"] or cid, "company_status": "troubled" if p["troubled"] else "active",
        "company_type": p["legal_form"], "incorporated": p["registered"], "sic_codes": p["pkd_main"] + p["pkd_other"],
        "search_code": code, "locality": p["city"], "region": p["voivodeship"], "stage": "screened",
        "source": SOURCE})
    url = f"{REGISTER} (KRS {p['krs']})"
    for i, person in enumerate(p["shareholders"]):
        store.save_owner(conn, client, cid, {
            "person_key": f"krs:shareholder:{i}:{person['name']}", "name": person["name"],
            "kind": "psc_corporate" if person["corporate"] else "psc_individual", "role": "shareholder",
            "birth_year": person["birth_year"], "birth_month": person["birth_month"], "appointed_on": None,
            "ceased_on": None, "ownership": "100" if person["whole"] else (str(person["shares"]) + " shares"
                                                                         if person["shares"] else None),
            "source": url})
    for i, person in enumerate(p["board"]):
        store.save_owner(conn, client, cid, {
            "person_key": f"krs:board:{i}:{person['name']}", "name": person["name"], "kind": "director",
            "role": person["role"], "birth_year": person["birth_year"], "birth_month": person["birth_month"],
            "appointed_on": None, "ceased_on": None, "ownership": None, "source": url})
    put = lambda claim, value, status, step=None: store.record_evidence(conn, client, cid, claim, value, status, url, step)
    put("Registered in KRS", p["registered"], "public")
    put("Main activity (PKD)", ", ".join(p["pkd_main"]), "public")
    put("Share capital", f"{p['capital_pln']:,.0f} PLN" if p["capital_pln"] else None, "public")
    last = p["filed_accounts"][0] if p["filed_accounts"] else {}
    put("Latest annual accounts filed", f"{last.get('filed')} (period to {last.get('period_end')})" if last else None,
        "public" if last else "unknown")
    for claim in ("Revenue", "EBITDA", "Employees", "Net assets"):
        put(claim, None, "unknown", "Filed statement (RDF) via rejestr.io, or ask the owner")
    put("Owner age", None if owner_age(p, today or date.today()) is None else str(owner_age(p, today or date.today())),
        "public" if owner_age(p, today or date.today()) is not None else "unknown", "Ask the owner")
    return cid


def run(conn, client: str, eta: dict, krs: KRSClient, days: list[str], max_new: int | None = None,
        today: date | None = None) -> dict:
    ensure_schema(conn)
    pl = eta.get("pl") or {}
    sieve = pl.get("sieve1") or {}
    out = {"days": 0, "numbers": 0, "read": 0, "kept": 0, "pass": 0, "review": 0, "fail": 0, "skipped": {},
           "fails": {}}
    seen = {r["krs"] for r in conn.execute("SELECT krs FROM eta_pl_seen WHERE client=?", (client,))}
    try:
        for day in days:
            numbers = [n for n in dict.fromkeys(krs.bulletin(day)) if n not in seen]
            out["days"] += 1
            out["numbers"] += len(numbers)
            for number in numbers:
                if max_new is not None and out["read"] >= max_new:
                    return out
                odpis = krs.extract(number)
                out["read"] += 1
                seen.add(number)
                if not odpis:
                    reason = "not_in_register_p"
                else:
                    p = parse(odpis)
                    reason = keep_reason(p, pl)
                    if not reason:
                        cid = save(conn, client, p, pl, today)
                        verdict, score, fails, breakdown = evaluate(p, sieve, today)
                        store.save_screen(conn, client, cid, 1, verdict, score, fails, breakdown,
                                          {k: p[k] for k in ("registered", "pkd_main", "capital_pln", "troubled")}
                                          | {"owner_age": owner_age(p, today or date.today()),
                                             "accounts_filed": len(p["filed_accounts"])})
                        out["kept"] += 1
                        out[verdict] += 1
                        for f in fails:
                            out["fails"][f] = out["fails"].get(f, 0) + 1
                if reason:
                    out["skipped"][reason] = out["skipped"].get(reason, 0) + 1
                conn.execute("INSERT OR REPLACE INTO eta_pl_seen(client, krs, kept, reason, checked_at)"
                             " VALUES (?,?,?,?,?)", (client, number, int(not reason), reason, db.now_iso()))
                conn.commit()
    except KRSUnavailable as exc:
        out["stopped"] = str(exc)
    return out


def days_back(end: date, count: int) -> list[str]:
    """The last `count` working days up to `end` (the bulletin is published on working days)."""
    out, day = [], end
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return out
