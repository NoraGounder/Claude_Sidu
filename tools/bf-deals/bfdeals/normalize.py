"""Stage 2: turn raw Firecrawl / Alexandria output into one offer schema.

Raw files live in data/raw/. Three shapes are understood:
  * Alexandria batch results ({"data": {"alexandria": [...]}}) from
    mydealz-de, hotukdeals-com, slickdeals-net, tweakers-net, amazon-com.
  * {"kind": "offers", ...}   offers already in the schema (scrape extracts).
  * {"kind": "wishlist", ...} an Amazon wishlist export.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MARKET = {
    "mydealz-de": ("DE", "EUR"),
    "hotukdeals-com": ("UK", "GBP"),
    "slickdeals-net": ("US", "USD"),
    "tweakers-net": ("NL", "EUR"),
    "amazon-com": ("US", "USD"),
    "mediaexpert-pl": ("PL", "PLN"),
}

# Order matters: the first match wins, so specific models come before families.
ROBOROCK_MODELS = [
    r"saros 20 flow", r"saros 20 sonic", r"saros 20 neo", r"saros 20x", r"saros 20",
    r"saros z70", r"saros 10r", r"saros 10",
    r"qrevo edge 3 pro", r"qrevo edge 2 flowx", r"qrevo edge 2 flow", r"qrevo edge 2 pro", r"qrevo edge 2x", r"qrevo edge 2",
    r"qrevo curv 2 flowx", r"qrevo curv 2 flow", r"qrevo curv 2 pro", r"qrevo curv 2",
    r"qrevo edge 5v1", r"qrevo curv 5a1", r"qrevo curv", r"q8 max\+", r"q8 max", r"q10 s5\+", r"q10 s5",
    r"s8 maxv ultra", r"q10 vf\+", r"q10 vf",
    r"qrevo s pro", r"qrevo 2 pro", r"qrevo 5ae", r"qrevo maxv", r"qv 35a",
    r"q10 s5\+", r"q7 l5\+", r"q7 l5", r"q7 m5\+", r"q7 m5",
]
NOT_A_ROBOT_VACUUM = re.compile(
    r"m[äa]hroboter|lawn|mower|rockneo|rockmow|\bf25\b|\bfx25\b|\bh60\b|nass|wet and dry|wet dry|stick vacuum|akku-staubsauger",
    re.I,
)

DIGITAL_EXCLUDE = re.compile(
    r"higgsfield|logicc|kurs\b|schulung|course|academy|guthaben|aws free|reset|van damme|colab|"
    r"cloud credit|pixel|asus|telekom|n26|smart tv|\blg\b|logitech|mouse|headphones|wh-1000|"
    r"chromebook|shield|uber one|amex|visa card|duck\.ai|kopfh|api-credits|nutzungslimit|feature|"
    r"photoshop|vodafone|flights|open-source|includes youtube",
    re.I,
)
DIGITAL = [
    (r"adobe creative cloud", "software", "Adobe Creative Cloud"),
    (r"google ai pro|gemini", "llm", "Google AI Pro"),
    (r"chatgpt", "llm", "ChatGPT"),
    (r"perplexity", "llm", "Perplexity Pro"),
    (r"\bclaude\b(?!.*van damme)", "llm", "Claude"),
    (r"typingmind", "llm", "TypingMind (BYOK)"),
    (r"microsoft 365|office 365", "software", "Microsoft 365"),
    (r"nordvpn", "software", "NordVPN"),
    (r"proton ?vpn", "software", "Proton VPN"),
    (r"windscribe", "software", "Windscribe VPN"),
    (r"surfshark", "software", "Surfshark VPN"),
    (r"1password", "software", "1Password"),
    (r"kindle\+? ?unlimited", "membership", "Kindle Unlimited"),
    (r"\baudible\b", "membership", "Audible"),
    (r"\beconomist\b", "membership", "The Economist"),
    (r"financial times", "membership", "Financial Times"),
]
COMICS = re.compile(r"graphic novel|\bmanga\b|comic|box set", re.I)
COMICS_EXCLUDE = re.compile(r"doll|marker|pad|xbox|game bundle|figure|perfume|parfum|serum|watch", re.I)

FLAG_RULES = [
    (r"\b(lebanon|nigeria|brazil|turkey|india|argentina|egypt)\b.*\bvpn\b|\bvia \w+ vpn\b", "vpn_region_trick"),
    (r"personali[sz]", "personalised"),
    (r"student|studenten|unidays|teacher", "student_only"),
    (r"forschende|wissenschaftler|research|nonprofit|non-profit", "eligibility_restricted"),
    (r"cashback", "cashback_required"),
    (r"refurb", "refurbished"),
    (r"\blokal\b|in-store|in store", "in_store_only"),
    (r"existing members|bestandskunden", "existing_members_only"),
    (r"neukunden|new customers|new members", "new_customers_only"),
    (r"selected accounts|ausgew[äa]hlte", "selected_accounts"),
    (r"kindle edition", "ebook_gift"),
    (r"benefits\.me|beans id|corporate benefits|mitarbeiterangebot", "eligibility_restricted"),
]


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def classify(title: str, query: str = "") -> tuple[str, str] | None:
    t = title.lower()
    if "roborock" in t or "roborock" in query.lower():
        if NOT_A_ROBOT_VACUUM.search(t):
            return None
        for pat in ROBOROCK_MODELS:
            if re.search(pat, t):
                name = re.sub(r"\\", "", pat).title().replace("Qv", "QV").replace("Ae", "AE").replace("Maxv", "MaxV").replace("Flowx", "FlowX").replace("5V1", "5V1").replace("Vf", "VF").replace("S8 Maxv", "S8 MaxV")
                return "vacuum", f"Roborock {name}"
        return None
    for pat, cat, item in DIGITAL:
        if re.search(pat, t):
            return None if DIGITAL_EXCLUDE.search(t) else (cat, item)
    if COMICS.search(t) and not COMICS_EXCLUDE.search(t):
        return "comics", re.split(r" [-–(|] | - ", title)[0].strip()[:70]
    return None


def flags_for(text: str) -> list[str]:
    return sorted({flag for pat, flag in FLAG_RULES if re.search(pat, text, re.I)})


def _num(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


SINCE = "2026-10-15"  # deal posts older than this are treated as stale (overridable)


def _from_deal(provider: str, query: str, d: dict) -> dict | None:
    if d.get("is_expired") or (d.get("posted_at") or "9999")[:10] < SINCE:
        return None
    title = d.get("title") or ""
    hit = classify(title, query)
    if not hit:
        return None
    market, cur = MARKET[provider]
    price = _num(d.get("price"))
    merchant = d.get("merchant") or {}
    merchant = merchant.get("name") if isinstance(merchant, dict) else merchant
    merchant = merchant or d.get("store_slug") or d.get("store_domain") or "?"
    voucher = d.get("voucher_code") or d.get("coupon_code")
    flags = flags_for(title)
    if d.get("is_local"):
        flags = sorted(set(flags) | {"in_store_only"})
    return {
        "id": _id(provider, d.get("deal_id") or d.get("id"), title),
        "category": hit[0], "item": hit[1], "title": title[:160],
        "retailer": merchant, "market": market, "currency": cur,
        "price": price, "list_price": _num(d.get("next_best_price") or d.get("list_price")),
        "voucher": None if voucher in (None, "None") else voucher,
        "url": d.get("url"), "source": provider, "posted_at": (d.get("posted_at") or "")[:10],
        "votes": _num(d.get("temperature") or d.get("thumb_score")),
        "shipping": _num(d.get("shipping_price")), "flags": flags,
    }


def _from_mediaexpert(data: dict) -> list[dict]:
    """Media Expert listing: PLN shelf price, checkout-code price and the 30-day low (Omnibus)."""
    out = []
    for x in data.get("items", []):
        name, pr = x.get("name") or "", x.get("price") or {}
        hit = classify(name)
        if not hit or pr.get("current") is None:
            continue
        code = pr.get("with_code") or {}
        status = (x.get("availability") or {}).get("status")
        flags = {"not_available": ["unavailable"], "shops_only": ["in_store_only"]}.get(status, [])
        out.append({
            "id": _id("mediaexpert", x.get("offer_id") or x.get("product_id"), name),
            "category": hit[0], "item": hit[1], "title": name[:160], "retailer": "Media Expert",
            "market": "PL", "currency": "PLN", "price": float(code.get("price") or pr["current"]),
            "list_price": pr.get("list") or pr.get("current"), "low_30d": pr.get("lowest_30_days"),
            "voucher": code.get("code"), "url": x.get("url"), "source": "mediaexpert-pl",
            "posted_at": "", "votes": None, "shipping": None, "flags": flags,
        })
    return out


def _from_alexandria(blob: dict) -> list[dict]:
    out = []
    for r in blob["data"]["alexandria"]:
        provider, data = r.get("provider"), r.get("data") or {}
        if provider not in MARKET or r.get("error"):
            continue
        if provider == "mediaexpert-pl":
            out += _from_mediaexpert(data)
            continue
        query = data.get("query") or ""
        if "deals" in data:
            out += [o for d in data["deals"] if (o := _from_deal(provider, query, d))]
        for x in data.get("results", []):  # catalogue search (tweakers, amazon-com)
            name = x.get("name") or x.get("title") or ""
            hit = classify(name if "roborock" in name.lower() else f"roborock {name}", query)
            price = x.get("lowest_price") if "lowest_price" in x else (x.get("price") or {}).get("amount")
            if not hit or price is None or x.get("sponsored"):
                continue
            market, cur = MARKET[provider]
            out.append({
                "id": _id(provider, x.get("product_id") or x.get("asin"), name),
                "category": hit[0], "item": hit[1], "title": name[:160],
                "retailer": "Tweakers lowest" if provider == "tweakers-net" else "Amazon US",
                "market": market, "currency": cur, "price": float(price), "list_price": None,
                "voucher": None, "url": x.get("url"), "source": provider, "posted_at": "",
                "votes": None, "shipping": None, "flags": ["nl_shop"] if provider == "tweakers-net" else [],
            })
    return out


def _from_offers(blob: dict) -> list[dict]:
    out = []
    for o in blob["offers"]:
        o = {**{k: blob.get(k) for k in ("market", "currency", "source", "retailer", "category")}, **o}
        o.setdefault("flags", [])
        o.setdefault("list_price", None)
        o["id"] = o.get("id") or _id(o["source"], o["title"], o.get("price"))
        out.append(o)
    return out


def _from_wishlist(blob: dict) -> list[dict]:
    out = []
    for row in blob["items"]:
        title, author, fmt, price, list_price = (row + [None] * 5)[:5]
        kindle = fmt.lower().startswith("kindle")
        out.append({
            "id": _id("wishlist", title, fmt, price), "category": "books", "item": title,
            "title": f"{title} ({author})", "retailer": blob.get("retailer", "Amazon.de"),
            "market": blob["market"], "currency": blob["currency"], "price": price,
            "list_price": list_price, "format": "ebook" if kindle else "print",
            "voucher": None, "url": None, "source": "amazon-wishlist", "posted_at": blob.get("observed", ""),
            "votes": None, "shipping": None, "flags": [] if price is not None else ["unavailable"],
        })
    return out


def load_offers(raw_dir: Path, since: str | None = None) -> list[dict]:
    global SINCE
    SINCE = str(since) if since else SINCE
    offers: dict[str, dict] = {}
    for path in sorted(raw_dir.glob("*.json")):
        blob = json.loads(path.read_text())
        if blob.get("kind") == "offers":
            batch = _from_offers(blob)
        elif blob.get("kind") == "wishlist":
            batch = _from_wishlist(blob)
        elif "data" in blob and "alexandria" in blob["data"]:
            batch = _from_alexandria(blob)
        else:
            continue
        for o in batch:
            offers.setdefault(o["id"], o)
    return list(offers.values())
