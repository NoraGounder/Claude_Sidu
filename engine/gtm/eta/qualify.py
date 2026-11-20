"""Sieve 2: qualify sieve-1 survivors with the Stanford industry scorecard and Hamilton Helmer's 7 Powers.

2a  Industry (Stanford Primer, p.30): one TypeSafe Jev 1.14 decision per SIC code, ten criteria scored
    1-3 (fragmented, growing, recurring revenue, sizable, healthy margins, straightforward operations, barriers
    to entry, low customer concentration, no consolidation trend, low exogenous risk), out of 30. Cached in
    eta_industry and reused for every company in that code.
2b  Company (7 Powers): the company's own website is found by guessing its domain and accepted only when
    the site shows the company's registered number (UK law requires it on company websites). Jev 1.14 then
    rates each Power from its text: no evidence, some, or clear evidence of both a Benefit and a Barrier.
    Every Power found becomes an `unverified` claim in the evidence ledger, to test with the owner.

Verdict (eta_screen, sieve 2): qualified = sieve 1 pass, industry score >= min_score and at least
min_clear_powers Power with clear evidence; watch = anything short of that or unknown; not_qualified =
industry clearly below the bar. AI policy as everywhere: Jev 1.14 only, no fallback, every call logged.
"""

from __future__ import annotations

import json
import re

from gtm import budget, db
from gtm.config import ClientConfig
from gtm.eta import store
from gtm.sources.jev import JevClient, JevResult, check_policy, scrub

VENDOR = "openrouter"
CLEAR = 1.5          # Jev score 0-2: at or above this, the Power has clear evidence

SCHEMA = """
CREATE TABLE IF NOT EXISTS eta_industry (
    client      TEXT NOT NULL,
    sic_code    TEXT NOT NULL,
    label       TEXT,
    score       REAL NOT NULL,          -- out of 30
    answers     TEXT NOT NULL,          -- criterion -> 1..3
    model_id    TEXT NOT NULL,
    decided_at  TEXT NOT NULL,
    PRIMARY KEY (client, sic_code)
);
CREATE TABLE IF NOT EXISTS eta_websites (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    website         TEXT,                -- NULL: no site found that shows the company number
    tried           TEXT NOT NULL,
    checked_at      TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
CREATE TABLE IF NOT EXISTS eta_powers (
    client          TEXT NOT NULL,
    company_number  TEXT NOT NULL,
    website         TEXT NOT NULL,
    answers         TEXT NOT NULL,       -- power -> 0..2
    clear_powers    TEXT NOT NULL,       -- list of powers with clear evidence
    model_id        TEXT NOT NULL,
    decided_at      TEXT NOT NULL,
    PRIMARY KEY (client, company_number)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def price_key(cfg: ClientConfig) -> str:
    return f"openrouter:{cfg.ai['model']}:request"


def _log_call(conn, cfg: ClientConfig, result: JevResult | None, error: str | None) -> None:
    conn.execute(
        "INSERT INTO jev_calls(client, account_id, requested_model, model_id, input_tokens, output_tokens,"
        " cost_usd, latency_ms, request_id, status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cfg.slug, None, cfg.ai["model"], result.model_id if result else None,
         result.input_tokens if result else None, result.output_tokens if result else None,
         result.cost_usd if result else None, result.latency_ms if result else None,
         result.request_id if result else None, "succeeded" if result else "failed",
         scrub(error)[:500] if error else None, db.now_iso()))


def _ask(jev: JevClient, conn, cfg: ClientConfig, state: dict, questions: dict) -> JevResult:
    try:
        result = jev.decide(state, questions)
    except Exception as exc:
        _log_call(conn, cfg, None, str(exc))
        conn.commit()
        raise
    _log_call(conn, cfg, result, None)
    return result


# ---------- 2a: industry scorecard ----------

def industry_questions(eta: dict) -> dict:
    out = {}
    for key, text in (eta.get("industry_scorecard") or {}).get("criteria", {}).items():
        out[key] = {"type": "score",
                    "instructions": (f"For UK companies in this industry with roughly £8-24 million revenue, rate: "
                                     f"{text}. Use the Stanford Search Fund industry scorecard scale."),
                    "criteria": ["Low fit with the criterion (1)", "Medium fit (2)", "High fit (3)"]}
    return out


def score_industries(conn, cfg: ClientConfig, eta: dict, codes: dict[str, str], jev: JevClient | None = None,
                     redo: bool = False) -> dict:
    """Score each SIC code once (cached). Returns {code: score_out_of_30}."""
    ensure_schema(conn)
    check_policy(cfg.ai)
    done = {r["sic_code"]: r["score"] for r in conn.execute("SELECT sic_code, score FROM eta_industry WHERE client=?",
                                                            (cfg.slug,))}
    todo = {c: l for c, l in codes.items() if redo or c not in done}
    if todo:
        budget.check(conn, cfg, VENDOR, budget.estimate(cfg, price_key(cfg), len(todo)))
        jev = jev or JevClient(cfg.ai)
        questions = industry_questions(eta)
        for code, label in todo.items():
            state = {"country": "United Kingdom", "uk_sic_2007_code": code, "industry": label,
                     "buyer": "a first-time CEO buying one company to own and run for the long term (search fund)"}
            result = _ask(jev, conn, cfg, state, questions)
            answers = {k: round(1 + float(v["score"]), 2) for k, v in result.answers.items()}
            total = round(sum(answers.values()), 1)
            conn.execute("INSERT OR REPLACE INTO eta_industry(client, sic_code, label, score, answers, model_id,"
                         " decided_at) VALUES (?,?,?,?,?,?,?)",
                         (cfg.slug, code, label, total, json.dumps(answers), result.model_id, db.now_iso()))
            conn.commit()
            done[code] = total
    return {c: done[c] for c in codes if c in done}


# ---------- 2b: the company's website ----------

_SUFFIXES = {"limited", "ltd", "plc", "llp", "the", "uk", "co", "company", "and", "&"}


def domain_candidates(name: str) -> list[str]:
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower().replace("&", " and ")) if w]
    core = [w for w in words if w not in _SUFFIXES] or words
    stems = []
    for stem in ("".join(core), "-".join(core), "".join(core[:2]), "".join(core[:1])):
        if stem and len(stem) >= 3 and stem not in stems:
            stems.append(stem)
    return [f"{s}.{tld}" for s in stems for tld in ("co.uk", "com", "uk")]


def shows_number(text: str, number: str) -> bool:
    bare = number.lstrip("0")
    return bool(re.search(rf"(?<!\d)0*{re.escape(bare)}(?!\d)", text or "")) if bare else False


_LEGAL_LINKS = ("privacy", "terms", "legal", "contact", "about", "cookie", "imprint")


def find_website(fetcher, name: str, number: str, max_candidates: int = 8) -> tuple[str | None, list[str]]:
    """First candidate domain whose site shows the registered company number, on the home page or a
    legal/contact/about page linked from it. Returns (website or None, domains tried)."""
    tried = []
    for domain in domain_candidates(name)[:max_candidates]:
        url = f"https://www.{domain}/"
        tried.append(domain)
        page = fetcher.get(url)
        if not page.ok:
            continue
        if shows_number(page.text, number):
            return url, tried
        for link, anchor in page.links[:200]:
            if any(k in (link + " " + anchor).lower() for k in _LEGAL_LINKS) and domain in link:
                sub = fetcher.get(link)
                if sub.ok and shows_number(sub.text, number):
                    return url, tried
    return None, tried


def site_text(fetcher, website: str, limit: int = 4000) -> tuple[str, str]:
    home = fetcher.get(website)
    parts, title = [home.text], home.title
    for link, anchor in home.links[:200]:
        if any(k in (link + " " + anchor).lower() for k in ("about", "services", "what-we-do", "sectors", "clients")):
            sub = fetcher.get(link)
            if sub.ok:
                parts.append(sub.text)
            if sum(len(p) for p in parts) > limit * 2:
                break
    return title, " ".join(parts)[:limit]


def powers_questions(eta: dict) -> dict:
    out = {}
    for key, text in (eta.get("seven_powers") or {}).get("powers", {}).items():
        out[key] = {"type": "score",
                    "instructions": (f"Hamilton Helmer's 7 Powers. {text}. A Power needs both a Benefit (better cash "
                                     "flow: higher prices or lower costs) and a Barrier (competitors cannot copy it). "
                                     "Judge only from the company facts and website text given."),
                    "criteria": ["No evidence", "Some evidence", "Clear evidence of both Benefit and Barrier"]}
    return out


# ---------- run ----------

def candidates(conn, client: str, verdicts=("pass", "review")) -> list:
    marks = ",".join("?" for _ in verdicts)
    return conn.execute(
        f"SELECT c.*, s.verdict, s.score FROM eta_companies c JOIN eta_screen s ON s.client=c.client"
        f" AND s.company_number=c.company_number AND s.sieve=1 WHERE c.client=? AND s.verdict IN ({marks})"
        f" ORDER BY s.score DESC", (client, *verdicts)).fetchall()


def run(conn, cfg: ClientConfig, eta: dict, fetcher=None, jev: JevClient | None = None,
        limit: int | None = None) -> dict:
    ensure_schema(conn)
    check_policy(cfg.ai)
    rows = candidates(conn, cfg.slug)[: limit or (eta.get("qualification") or {}).get("max_websites_per_run", 200)]
    labels = {str(k): v for k, v in (eta.get("search", {}).get("sic_codes") or {}).items()}
    codes = {r["search_code"]: labels.get(r["search_code"], r["search_code"]) for r in rows if r["search_code"]}
    out = {"companies": len(rows), "industries_scored": 0, "websites_found": 0, "powers_decided": 0,
           "qualified": 0, "watch": 0, "not_qualified": 0}
    if not rows:
        return out
    jev = jev or JevClient(cfg.ai)
    industry = score_industries(conn, cfg, eta, codes, jev)
    out["industries_scored"] = len(industry)
    if fetcher is None:
        from gtm.crawl import default_fetcher
        fetcher = default_fetcher()

    sc, sp = eta.get("industry_scorecard") or {}, eta.get("seven_powers") or {}
    questions = powers_questions(eta)
    for row in rows:
        number = row["company_number"]
        cached = conn.execute("SELECT website FROM eta_websites WHERE client=? AND company_number=?",
                              (cfg.slug, number)).fetchone()
        if cached:
            website = cached["website"]
        else:
            website, tried = find_website(fetcher, row["name"], number)
            conn.execute("INSERT OR REPLACE INTO eta_websites(client, company_number, website, tried, checked_at)"
                         " VALUES (?,?,?,?,?)", (cfg.slug, number, website, json.dumps(tried), db.now_iso()))
        clear: list[str] | None = None
        if website:
            out["websites_found"] += 1
            prev = conn.execute("SELECT clear_powers FROM eta_powers WHERE client=? AND company_number=?",
                                (cfg.slug, number)).fetchone()
            if prev:
                clear = json.loads(prev["clear_powers"])
            else:
                budget.check(conn, cfg, VENDOR, budget.estimate(cfg, price_key(cfg), 1))
                title, text = site_text(fetcher, website)
                state = {"company": row["name"], "uk_sic_2007_code": row["search_code"],
                         "industry": labels.get(row["search_code"]), "website": website, "website_title": title, "website_text": text}
                result = _ask(jev, conn, cfg, state, questions)
                scores = {k: round(float(v["score"]), 2) for k, v in result.answers.items()}
                clear = [k for k, v in scores.items() if v >= CLEAR]
                conn.execute("INSERT OR REPLACE INTO eta_powers(client, company_number, website, answers, clear_powers,"
                             " model_id, decided_at) VALUES (?,?,?,?,?,?,?)",
                             (cfg.slug, number, website, json.dumps(scores), json.dumps(clear), result.model_id,
                              db.now_iso()))
                out["powers_decided"] += 1
            for power in clear:
                store.record_evidence(conn, cfg.slug, number, f"7 Powers: {power.replace('_', ' ')}",
                                      "website suggests it", "unverified", website,
                                      "Test with the owner: what is the Benefit, and why can competitors not copy it?")
        else:
            store.record_evidence(conn, cfg.slug, number, "Website", None, "unknown", None,
                                  "No site found that shows the company number; ask the owner")

        ind = industry.get(row["search_code"])
        if ind is not None:
            store.record_evidence(conn, cfg.slug, number, "Stanford industry score", f"{ind:g} of 30", "public",
                                  f"Jev 1.14 industry scorecard for SIC {row['search_code']}")
        min_ind, min_pow = sc.get("min_score", 22), sp.get("min_clear_powers", 1)
        if ind is not None and ind < min_ind - 4:
            verdict = "not_qualified"
        elif (row["verdict"] == "pass" and ind is not None and ind >= min_ind
              and clear is not None and len(clear) >= min_pow):
            verdict = "qualified"
        else:
            verdict = "watch"
        score = round((row["score"] * 0.5) + ((ind or 0) / 30 * 30) + (min(len(clear or []), 2) * 10), 1)
        store.save_screen(conn, cfg.slug, number, 2, verdict, score, [],
                          {"sieve1_score": row["score"], "industry_score": ind, "clear_powers": clear},
                          {"website": website})
        out[verdict] += 1
        conn.commit()
    return out


def qualified(conn, client: str, verdicts=("qualified", "watch")) -> list[dict]:
    marks = ",".join("?" for _ in verdicts)
    rows = conn.execute(
        f"SELECT c.company_number, c.name, c.search_code, c.locality, s.verdict, s.score, s.breakdown, s.metrics,"
        f" s1.score AS sieve1_score, s1.metrics AS sieve1_metrics FROM eta_companies c"
        f" JOIN eta_screen s ON s.client=c.client AND s.company_number=c.company_number AND s.sieve=2"
        f" JOIN eta_screen s1 ON s1.client=c.client AND s1.company_number=c.company_number AND s1.sieve=1"
        f" WHERE c.client=? AND s.verdict IN ({marks}) ORDER BY s.score DESC", (client, *verdicts)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("breakdown", "metrics", "sieve1_metrics"):
            d[k] = json.loads(d[k])
        out.append(d)
    return out
