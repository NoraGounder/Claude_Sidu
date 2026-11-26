"""Stage 3: what each offer really costs, delivered, in the report currency.

Physical goods
  home market   price + shipping
  EU market     price re-taxed at home VAT (OSS) + shipping; no customs
  UK / US       price (UK VAT is not refunded via a forwarder) + forwarder
                + duty + import VAT on (goods + freight + duty) + clearance fee
  gift market   bought and delivered inside the recipient's country
Digital goods   the vendor charges the buyer's VAT, so a US ex-tax price
                gets home VAT added and a UK/DE gross price is re-taxed.
"""
from __future__ import annotations

import json
import urllib.request

NBP_URL = "https://api.nbp.pl/api/exchangerates/tables/A/?format=json"
PHYSICAL = {"vacuum", "comics", "books"}


def fetch_fx(report_currency: str = "PLN") -> dict:
    """Mid rates from the National Bank of Poland, as units of PLN per currency."""
    if report_currency != "PLN":
        raise NotImplementedError("NBP rates are quoted in PLN; add another source for other currencies")
    with urllib.request.urlopen(NBP_URL, timeout=20) as r:
        table = json.load(r)[0]
    rates = {x["code"]: x["mid"] for x in table["rates"]}
    rates["PLN"] = 1.0
    return {"rates": rates, "table": table["no"], "date": table["effectiveDate"]}


def _vat(cfg, market, category, fmt=None):
    rates = cfg["landed_cost"]["vat"].get(market, {"standard": 0.0, "books": 0.0})
    return rates["books"] if category in ("books", "comics") else rates["standard"]


def assess(o: dict, cfg: dict, fx: dict) -> dict:
    """Add landed cost, a breakdown, warnings and blockers to one offer."""
    lc, home = cfg["landed_cost"], cfg["home_country"]
    rate = fx["rates"][o["currency"]]
    cat, market, price = o["category"], o["market"], o.get("price")
    warnings, blockers = [], []
    flags = set(o.get("flags", []))

    if price is None:
        return {**o, "landed": None, "breakdown": {}, "warnings": [], "blockers": ["no price shown"]}

    gift_market = (cfg.get("gift_delivery") or {}).get(cat)
    gift_market = "UK" if gift_market == "GB" else gift_market
    bd: dict[str, float] = {}

    if cat in PHYSICAL and o.get("format") != "ebook":
        ship = o.get("shipping") or 0.0
        merchant = (o.get("retailer") or "").lower()
        if gift_market:
            if market != gift_market:
                blockers.append(f"gift goes to {gift_market}; buy it there instead")
            bd["goods"] = price * rate
            bd["shipping"] = ship * rate
        elif market == home:
            bd["goods"], bd["shipping"] = price * rate, ship * rate
        elif market in ("DE", "NL", "FR", "IT", "ES", "AT"):
            goods = price
            if lc.get("eu_destination_vat"):
                goods = price / (1 + _vat(cfg, market, cat)) * (1 + _vat(cfg, home, cat))
            free = any(m in merchant for m in lc["eu_shipping"]["free_merchants"])
            if not ship and not free:
                ship = lc["eu_shipping"]["default"]
            bd["goods"], bd["shipping"] = goods * rate, ship * rate
        elif market in ("UK", "US"):
            size = "large" if cat == "vacuum" else "small"
            goods = price * (1 + (lc["us_sales_tax"] if market == "US" else 0))
            freight = lc["forwarder"][market][size]
            customs_value = (goods + freight) * rate
            duty = customs_value * lc["duty"].get(cat, 0.0)
            vat = (customs_value + duty) * _vat(cfg, home, cat)
            bd.update(goods=goods * rate, forwarder=freight * rate, duty=duty,
                      import_vat=vat, clearance=lc["customs_clearance_pln"])
            if market == "UK":
                warnings.append("UK VAT is paid and not refunded, then Polish VAT is charged on import")
        else:
            blockers.append(f"no cost model for market {market}")
    else:  # digital: subscriptions, software keys, e-books
        if cat == "books":  # Kindle price is tied to the account's store; take it as shown
            bd["goods"] = price * rate
        else:
            net = price / (1 + _vat(cfg, market, cat))
            bd["goods"] = net * (1 + _vat(cfg, home, cat)) * rate
            if market not in (home, "DE", "NL") and "global" not in flags:
                warnings.append(f"{market} offer: buy it from a {home} account; the local price can differ")

    # Compatibility and eligibility
    if cat == "vacuum" and market == "US":
        blockers.append("US model: 120 V dock and US plug, no EU warranty")
    if cat == "vacuum" and market == "UK":
        warnings.append("UK plug (adapter needed); warranty claims go through the UK seller")
    rules = {
        "vpn_region_trick": ("block", "needs a fake region via VPN, which breaks the service's terms"),
        "in_store_only": ("block", "in-store only"),
        "student_only": ("block", "students or teachers only"),
        "eligibility_restricted": ("block", "restricted eligibility (researchers / nonprofits)"),
        "unavailable": ("block", "not currently sold new"),
        "personalised": ("warn", "personalised offer: only some accounts see it"),
        "selected_accounts": ("warn", "selected accounts only"),
        "existing_members_only": ("warn", "existing members only"),
        "new_customers_only": ("warn", "new customers only"),
        "cashback_required": ("warn", "price depends on a cashback portal paying out"),
        "refurbished": ("warn", "refurbished"),
        "ebook_gift": ("warn", "e-book: lands in the buyer's own Kindle library, awkward as a gift"),
    }
    for f in sorted(flags):
        if f in rules:
            (blockers if rules[f][0] == "block" else warnings).append(rules[f][1])

    landed = round(sum(bd.values()), 2)
    return {**o, "landed": landed, "breakdown": {k: round(v, 2) for k, v in bd.items()},
            "warnings": warnings, "blockers": blockers}
