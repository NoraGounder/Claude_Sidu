"""Roborock price-to-performance: feature score, Pareto frontier, tier winners."""
from __future__ import annotations

import math
from pathlib import Path

import yaml

POINTS = {
    "mop": {"pad": 4, "vibra": 10, "rotating": 13, "rotating_ext": 16, "sonic": 17, "roller": 20},
    "dock": {"none": 0, "empty": 7, "allinone": 14, "hotwash": 17, "premium": 20},
    "nav": {"lidar": 7, "lidar_ai": 12, "starsight": 15},
    "mobility": {"std": 3, "slim": 6, "lift": 8, "arm": 8, "lift3": 10},
    "year": {2023: 2, 2024: 5, 2025: 8, 2026: 10},
}
TIERS = [("entry", 0, 1200), ("mid", 1200, 2500), ("premium", 2500, 1e9)]  # landed zł


def load_specs(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def perf_score(spec: dict) -> float:
    suction = 25 * max(0.0, min(1.0, math.log(spec["pa"] / 4000) / math.log(9)))
    return round(suction + sum(POINTS[k][spec[k]] for k in ("mop", "dock", "nav", "mobility", "year")), 1)


def lineup(offers: list[dict], specs: dict) -> list[dict]:
    """One row per Roborock model: best eligible landed price, PL reference, score, value."""
    rows: dict[str, dict] = {}
    for o in offers:
        if o["category"] != "vacuum" or o.get("landed") is None:
            continue
        r = rows.setdefault(o["item"], {"item": o["item"], "best": None, "pl_now": None, "pl_30d_low": None,
                                        "n_offers": 0, "markets": set()})
        r["n_offers"] += 1
        if o["market"] == "PL" and not o["blockers"]:
            r["pl_now"] = min(filter(None, [r["pl_now"], o["landed"]]))
            if o.get("low_30d"):
                r["pl_30d_low"] = min(filter(None, [r["pl_30d_low"], o["low_30d"]]))
        if not o["blockers"]:
            r["markets"].add(o["market"])
            if r["best"] is None or o["landed"] < r["best"]["landed"]:
                r["best"] = o
    out = []
    for r in rows.values():
        spec = specs.get(r["item"])
        best = r["best"]
        r["markets"] = sorted(r["markets"])
        r["rubric"] = perf_score(spec) if spec else None
        r["rtings"] = spec.get("rtings") if spec else None
        r["tested"] = r["rtings"] is not None
        r["score"] = round(r["rtings"] * 10, 1) if r["tested"] else None  # filled in below for untested
        r["confidence"] = spec.get("confidence") if spec else None
        r["spec"] = {k: spec[k] for k in ("year", "pa", "mop", "dock", "nav", "mobility")} if spec else None
        r["landed"] = best["landed"] if best else None
        ref = r["pl_30d_low"] or r["pl_now"]
        r["vs_pl_pct"] = round(100 * (1 - r["landed"] / ref), 1) if (ref and r["landed"]) else None
        r["tier"] = next((t for t, lo, hi in TIERS if r["landed"] and lo <= r["landed"] < hi), None)
        out.append(r)

    # Untested models: map the feature rubric onto the RTINGS scale with a least-squares line
    # fitted on the tested models, and mark the result as an estimate.
    pts = [(r["rubric"], r["score"]) for r in out if r["tested"] and r["rubric"]]
    if len(pts) >= 3:
        n = len(pts); mx = sum(x for x, _ in pts) / n; my = sum(y for _, y in pts) / n
        sxx = sum((x - mx) ** 2 for x, _ in pts) or 1.0
        slope = sum((x - mx) * (y - my) for x, y in pts) / sxx
        for r in out:
            if not r["tested"] and r["rubric"]:
                r["score"] = round(min(my + slope * (r["rubric"] - mx), max(y for _, y in pts)), 1)
    for r in out:
        r["value"] = round(r["score"] / (r["landed"] / 1000), 1) if (r["score"] and r["landed"]) else None

    # Pareto frontier: no other model is both cheaper (or equal) and higher-scoring.
    scored = sorted((r for r in out if r["value"]), key=lambda r: (r["landed"], -r["score"]))
    top = -1.0
    for r in scored:
        r["frontier"] = r["score"] > top
        top = max(top, r["score"])
    for tier, *_ in TIERS:
        in_tier = [r for r in scored if r["tier"] == tier]
        if in_tier:
            max(in_tier, key=lambda r: r["value"])["tier_winner"] = True
    return sorted(out, key=lambda r: (r["value"] is None, -(r["value"] or 0)))


def deterministic_deal(rows: list[dict]) -> dict | None:
    """Fallback 'deal of the century': lab-tested model scoring >= 7.5 with the best value."""
    cands = [r for r in rows if r.get("tested") and (r["score"] or 0) >= 75 and r["value"]]
    return max(cands, key=lambda r: r["value"]) if cands else None
