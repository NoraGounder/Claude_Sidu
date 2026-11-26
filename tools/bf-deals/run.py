#!/usr/bin/env python3
"""Run stages 2-5 of the deal scout over the raw scrape in data/raw/.

    python run.py                       # full run, Jev Router verdict
    python run.py --no-llm              # deterministic picks only
    python run.py --config my.yaml --raw data/raw --out data/out
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import yaml

from bfdeals.landed import assess, fetch_fx
from bfdeals.normalize import load_offers
from bfdeals.rank import ask_jev, build_payload, fallback_verdict, shortlist, validate
from bfdeals.score import deterministic_deal, lineup, load_specs
from bfdeals.report import render_html, render_md

HERE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=HERE / "config.local.yaml")
    ap.add_argument("--raw", default=HERE / "data/raw")
    ap.add_argument("--out", default=HERE / "data/out")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--reuse-verdict", action="store_true", help="re-render from the last saved verdict")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        cfg_path = HERE / "config.example.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    fx = fetch_fx(cfg["report_currency"])
    offers = [assess(o, cfg, fx) for o in load_offers(Path(args.raw), cfg.get("deals_since"))]
    by_id = {o["id"]: o for o in offers}
    (out / "offers.json").write_text(json.dumps(offers, indent=1, ensure_ascii=False))

    short = shortlist(offers)
    rows = lineup(offers, load_specs(HERE / "specs/roborock.yaml"))
    payload = build_payload(short, cfg, fx, rows)
    (out / "payload.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"{len(offers)} offers, shortlist: " + ", ".join(f"{k}={len(v)}" for k, v in short.items()))

    model, usage, problems = "deterministic (cheapest landed)", {}, []
    verdict_file = out / "verdict.json"
    if args.reuse_verdict and verdict_file.exists():
        saved = json.loads(verdict_file.read_text())
        verdict, model, usage = saved["verdict"], saved["model"], saved.get("usage", {})
    elif args.no_llm:
        verdict = fallback_verdict(short, deterministic_deal(rows))
    else:
        try:
            res = ask_jev(payload, cfg)
            verdict, model, usage = res["verdict"], f"{cfg['llm']['model']} → {res['model']}", res["usage"]
            verdict_file.write_text(json.dumps({"verdict": verdict, "model": model, "usage": usage}, indent=1))
        except Exception as e:  # network, budget or JSON failure: keep the run useful
            print(f"Jev Router failed ({e}); falling back to deterministic picks")
            verdict = fallback_verdict(short, deterministic_deal(rows))
    verdict, problems = validate(verdict, by_id)
    for p in problems:
        print("warning:", p)

    # Run-to-run history: what each model cost last time, and alerts on real drops.
    now = dt.datetime.now(dt.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    hist_file = out / "history.jsonl"
    history = [json.loads(line) for line in hist_file.read_text().splitlines()] if hist_file.exists() else []
    prev = history[-1]["prices"] if history else {}
    snap = {r["item"]: r["landed"] for r in rows if r["landed"]}
    deal_id = (verdict.get("vacuum") or {}).get("deal_of_the_century")
    alerts = [f"{k.replace('Roborock ', '')}: {prev[k]:,.0f} → {v:,.0f} zł ({100 * (v / prev[k] - 1):+.0f}%)"
              for k, v in snap.items() if prev.get(k) and v <= prev[k] * 0.95]
    if history and deal_id and history[-1].get("deal_id") != deal_id:
        alerts.insert(0, f"New deal of the century: {by_id[deal_id]['item']} at {by_id[deal_id]['landed']:,.0f} zł")
    with hist_file.open("a") as f:
        f.write(json.dumps({"at": now, "prices": snap, "deal_id": deal_id}) + "\n")
    (out / "alerts.json").write_text(json.dumps(alerts, indent=1, ensure_ascii=False))
    for a in alerts:
        print("ALERT:", a)

    sources = sorted({o["source"] for o in offers})
    scraped = max((o.get("posted_at") or "" for o in offers if o["source"] == "amazon-wishlist"), default="")
    ctx = {"verdict": verdict, "shortlist": short, "offers_by_id": by_id, "fx": fx, "model": model,
           "n_offers": len(offers), "sources": sources, "checks": cfg.get("checks", []),
           "lineup": rows, "prev": prev, "run_at": now, "scraped": scraped or dt.date.today().isoformat()}
    (out / "report.html").write_text(render_html(ctx))
    (out / "report.md").write_text(render_md(ctx))
    cost = usage.get("cost")
    print(f"verdict by {model}" + (f", cost ${cost:.4f}" if cost else "") + f" -> {out / 'report.html'}")


if __name__ == "__main__":
    main()
