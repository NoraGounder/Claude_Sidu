"""Budget guard: no paid call may push a vendor past its monthly cap in limits.yaml."""

from __future__ import annotations

from gtm import db
from gtm.config import ClientConfig


class BudgetExceeded(RuntimeError):
    pass


def estimate(cfg: ClientConfig, price_key: str, items: int) -> float:
    price = cfg.limits.unit_price_usd.get(price_key)
    if price is None:
        raise KeyError(f"No unit price for '{price_key}' in limits.yaml; add one before running.")
    return round(price * items, 4)


def check(conn, cfg: ClientConfig, vendor: str, est_cost: float) -> dict:
    cap = cfg.limits.month_budget_usd.get(vendor)
    if cap is None:
        raise BudgetExceeded(f"No monthly budget for vendor '{vendor}' in limits.yaml.")
    spent = db.month_spend(conn, cfg.slug, vendor)
    remaining = round(cap - spent, 4)
    if est_cost > remaining:
        raise BudgetExceeded(
            f"{vendor}: this run is estimated at ${est_cost:.2f}, but only ${remaining:.2f} of the "
            f"${cap:.2f} monthly budget is left (spent ${spent:.2f}). Lower --max-items or ask to raise the cap."
        )
    return {"vendor": vendor, "cap": cap, "spent": spent, "remaining": remaining, "estimate": est_cost}
