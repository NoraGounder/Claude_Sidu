"""Signal Sample: the free first step of a client's offer (Quailworks: decisions.md Q31).

For a prospect who asks for it: search the prospect's own market, read each company's website and job
board, and write the companies with the strongest buying signals, each with a quote and its source, to
data/samples/<name>.md for a person to check and send. Company-level data only. The companies belong
to the prospect's market, not to this client's pipeline, so nothing is stored as an account: only the
run and its cost are logged. Signals and weights come from clients/<client>/sample.yaml.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

from gtm import budget, db
from gtm.config import ClientConfig, data_dir
from gtm.crawl import crawl_site, default_fetcher
from gtm.layers.l1_discover import ACTOR, PAGE_SIZE, VENDOR, normalise
from gtm.signals import SignalRules, extract
from gtm.sources.apify import ApifyClient

PRICE_KEY = f"{ACTOR}:full"


def load_config(cfg: ClientConfig) -> dict:
    with (Path(cfg.root) / "sample.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def plan(cfg: ClientConfig, search: str | None, industry_ids: list[str], locations: list[str],
         max_items: int | None = None) -> tuple[dict, float]:
    conf = load_config(cfg)
    limit = max_items or conf.get("max_items", 60)
    actor_input = {"scraperMode": "full", "maxItems": limit, "locations": locations,
                   "companySize": conf["company_sizes"], "startPage": 1, "takePages": -(-limit // PAGE_SIZE)}
    if industry_ids:
        actor_input["industryIds"] = [str(i) for i in industry_ids][:20]
    if search:
        actor_input["searchQuery"] = search
    return actor_input, budget.estimate(cfg, PRICE_KEY, limit)


def find_signals(conf: dict, site, roles: list[str]) -> list[dict]:
    """[{signal, label, quote, url, weight}] for one company, strongest first, one per signal."""
    weights = conf["signals"]
    found: list[dict] = []
    # Roles the prospect's product is bought for: exact open job titles only (job links and job boards).
    hiring = [r.strip() for r in [*conf.get("hiring_roles", []), *roles] if r.strip()]
    open_role = next((t for t in site.job_titles if any(re.search(re.escape(r), t, re.I) for r in hiring)), None)
    source = site.board_url or (site.careers.url if site.careers and site.careers.ok else site.home.url)
    if open_role:
        found.append({"signal": "hiring", "label": "Hiring", "quote": open_role, "url": source,
                      "weight": weights.get("hiring", 0)})
    if len(site.job_titles) >= conf.get("growth_min_open_roles", 8):
        found.append({"signal": "growth", "label": "Growing", "quote": f"{len(site.job_titles)} open roles listed",
                      "url": source, "weight": weights.get("growth", 0)})
    rules = SignalRules({s: [(r["label"], r["pattern"]) for r in entries] for s, entries in conf["detect"].items()},
                        frozenset(), frozenset(), int(conf.get("quote_width", 110)), 1)
    seen = {f["signal"] for f in found}
    for e in extract(site, rules):
        if e.signal not in seen and weights.get(e.signal):
            seen.add(e.signal)
            found.append({"signal": e.signal, "label": e.label, "quote": e.quote, "url": e.url,
                          "weight": weights[e.signal]})
    return sorted(found, key=lambda f: -f["weight"])


def run(cfg: ClientConfig, conn, name: str, actor_input: dict, est_cost: float, roles: list[str] | None = None,
        top: int = 10, client: ApifyClient | None = None, fetcher_factory=None, workers: int = 8) -> dict:
    conf = load_config(cfg)
    budget.check(conn, cfg, VENDOR, est_cost)
    run_id = db.start_run(conn, cfg.slug, "SAMPLE", VENDOR, f"sample:{name}", est_cost, actor_input)
    try:
        outcome = (client or ApifyClient()).run_actor(ACTOR, actor_input)
    except Exception as exc:
        db.finish_run(conn, run_id, "failed", 0, None, str(exc)[:500])
        raise
    cost = round(max(outcome.cost_usd or 0.0, len(outcome.items) * cfg.limits.unit_price_usd.get(PRICE_KEY, 0.0)), 4)
    companies = [c for c in (normalise(i) for i in outcome.items) if c["website"] and c["name"]]
    fetcher_factory = fetcher_factory or default_fetcher
    boards = {"countries": conf.get("job_board_countries", [])}

    def read(company):
        try:
            site = crawl_site(fetcher_factory(), company["website"], job_boards=boards)
        except Exception:   # noqa: BLE001 - one bad site must not stop the sample
            return company, []
        return company, find_signals(conf, site, roles or []) if site.home.ok else []

    # A company is listed only with enough points: a certificate or a trade show alone is no reason to call.
    floor = conf.get("min_points", 0)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        scored = [(c, s) for c, s in pool.map(read, companies) if sum(f["weight"] for f in s) >= max(floor, 1)]
    scored.sort(key=lambda cs: (-sum(f["weight"] for f in cs[1]), cs[0]["name"]))
    picked = scored[:top]

    out_dir = data_dir() / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.md"
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [f"# Signal Sample: {name} ({today})", "",
             f"Market searched: {actor_input.get('searchQuery') or 'industry search'}, "
             f"{', '.join(actor_input['locations'])}. Companies read: {len(companies)}; with a signal: {len(scored)}.",
             "Check every line before sending: each quote must be true and current.", ""]
    for n, (c, signals) in enumerate(picked, start=1):
        where = ", ".join(x for x in [c.get("city"), c.get("country")] if x)
        size = f", {c['employee_range']} employees" if c.get("employee_range") else ""
        lines.append(f"{n}. **{c['name']}** ({c['website']}{size}{', ' + where if where else ''})")
        for f in signals[:3]:
            lines.append(f"   - {f['label']}: \"{f['quote']}\" ({f['url']})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    db.finish_run(conn, run_id, "succeeded", len(outcome.items), cost,
                  json.dumps({"companies_read": len(companies), "with_signal": len(scored), "listed": len(picked)}))
    return {"path": path, "fetched": len(outcome.items), "read": len(companies), "with_signal": len(scored),
            "listed": len(picked), "cost_usd": cost}
