"""Stage 5: render the verdict as an artifact-ready HTML page and a Markdown copy."""
from __future__ import annotations

from html import escape

ORDER = [
    ("vacuum", "Robot vacuum"),
    ("comics", "Comics gift"),
    ("books", "Wishlist books"),
    ("llm", "LLM subscriptions"),
    ("software", "Software"),
    ("membership", "Memberships"),
    ("toolkit", "Acquisition toolkit"),
]
SYM = {"EUR": "€", "GBP": "£", "USD": "$", "PLN": "zł"}


def money(v, cur="PLN"):
    if v is None:
        return "–"
    s = f"{v:,.2f}".replace(",", " ")
    return f"{s} zł" if cur == "PLN" else f"{SYM.get(cur, cur)}{s}"


def _roles(v: dict, cat: str) -> list[tuple[str, str]]:
    """(offer id, label) in display order, without repeats."""
    pairs = [(v.get("deal_of_the_century"), "Deal of the century"), (v.get("pick"), "Pick"),
             (v.get("runner_up"), "Runner-up")]
    pairs += [(i, f"Best {t}") for t, i in (v.get("tier_picks") or {}).items()]
    pairs += [(i, "Buy now" if cat == "books" else "Pick") for i in (v.get("picks") or []) + (v.get("buy_now") or [])]
    pairs += [(i, "Free") for i in v.get("free") or []]
    seen, out = set(), []
    for i, label in pairs:
        if i and i not in seen:
            seen.add(i)
            out.append((i, label))
    return out


def _ids(v: dict) -> list[str]:
    return [i for i, _ in _roles(v, "")]


def _lineup_table(rows: list[dict], prev: dict) -> str:
    out = []
    for r in rows:
        if not r["landed"]:
            continue
        b = r["best"]
        star = "★ " if r.get("frontier") else ""
        tier = f"{r['tier']}{' · best' if r.get('tier_winner') else ''}" if r["tier"] else ""
        delta = ""
        if r["item"] in prev and prev[r["item"]]:
            d = r["landed"] - prev[r["item"]]
            delta = f"{d:+,.0f}".replace(",", " ") if abs(d) >= 1 else "="
        vs = f"{-r['vs_pl_pct']:+.0f}%" if r["vs_pl_pct"] is not None else ""
        score = f"{r['score']:.0f}" + (" ?" if r["confidence"] == "low" else "") if r["score"] else "–"
        out.append(f"<tr><td>{star}{escape(r['item'].replace('Roborock ', ''))}</td><td class='r'>{score}</td>"
                   f"<td class='r'><b>{money(r['landed'])}</b></td><td>{escape(b['retailer'])} · {escape(b['market'])}"
                   f"{' · ' + escape(b['voucher']) if b.get('voucher') else ''}</td>"
                   f"<td class='r'>{money(r['pl_30d_low'] or r['pl_now'])}</td><td class='r'>{vs}</td>"
                   f"<td class='r'>{r['value'] if r['value'] else '–'}</td><td>{tier}</td><td class='r'>{delta}</td></tr>")
    return f"""<div class="scroll"><table>
<thead><tr><th>Model</th><th class='r'>Score</th><th class='r'>Best landed</th><th>Where</th><th class='r'>PL ref</th>
<th class='r'>vs PL</th><th class='r'>Pts / 1k zł</th><th>Tier</th><th class='r'>Δ last run</th></tr></thead>
<tbody>{''.join(out)}</tbody></table></div>
<p class="fine">★ = price-performance frontier (no cheaper model scores higher). Score = feature rubric in specs/roborock.yaml,
not a lab test; "?" = low-confidence specs. PL ref = Media Expert 30-day low where shown, else today's lowest Polish price.</p>"""


def _card(o: dict, role: str, ref: float | None) -> str:
    save = ""
    if ref and o["landed"] and o["landed"] < ref:
        save = f'<span class="tag">−{100 * (1 - o["landed"] / ref):.0f}% vs PL</span>'
    elif o.get("list_price") and o.get("price") and o["price"] < o["list_price"]:
        save = f'<span class="tag">−{100 * (1 - o["price"] / o["list_price"]):.0f}% vs list</span>'
    notes = "".join(f"<li>{escape(w)}</li>" for w in o["warnings"])
    link = f'<a href="{escape(o["url"])}" target="_blank" rel="noopener">Open deal</a>' if o.get("url") else ""
    code = f'<span class="code">code {escape(o["voucher"])}</span>' if o.get("voucher") else ""
    return f"""
<article class="pick">
  <div class="role">{escape(role)}</div>
  <h3>{escape(o['item'])}</h3>
  <p class="where">{escape(o['retailer'])} · {escape(o['market'])} · {money(o['price'], o['currency'])} {code}</p>
  <p class="landed"><span class="num">{money(o['landed'])}</span> landed {save}</p>
  {f'<ul class="notes">{notes}</ul>' if notes else ''}
  {link}
</article>"""


def _table(items: list[dict], show_blocked=True) -> str:
    rows = []
    for e in items:
        best = e["offers"][0] if e["offers"] else None
        if best:
            vs = f'{e["saving_vs_ref_pct"]:+.0f}%' if e.get("saving_vs_ref_pct") is not None and e.get("home_ref_pln") else ""
            vs = vs.replace("+", "−", 1) if vs.startswith("+") else vs.replace("-", "+", 1)
            rows.append(f"<tr><td>{escape(e['item'])}</td><td>{escape(best['retailer'])}</td>"
                        f"<td>{escape(best['market'])}</td><td class='r'>{money(best['price'], best['currency'])}</td>"
                        f"<td class='r'><b>{money(best['landed'])}</b></td><td class='r'>{money(e.get('home_ref_pln'))}</td>"
                        f"<td class='r'>{vs}</td></tr>")
        elif show_blocked and e["blocked"]:
            b = e["blocked"][0]
            rows.append(f"<tr class='blocked'><td>{escape(e['item'])}</td><td>{escape(b['retailer'])}</td>"
                        f"<td>{escape(b['market'])}</td><td class='r'>{money(b['price'], b['currency'])}</td>"
                        f"<td class='r'>{money(b['landed'])}</td><td colspan='2'>{escape('; '.join(b['blockers']))}</td></tr>")
    return f"""<div class="scroll"><table>
<thead><tr><th>Item</th><th>Best shop</th><th>Mkt</th><th class='r'>Price</th><th class='r'>Landed</th><th class='r'>PL ref</th><th class='r'>vs PL</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


CSS = """
/* Layout: one reading column; each category = verdict, pick cards, then the evidence table. */
:root{
  --paper:#f4f6f3; --card:#ffffff; --ink:#1b1f1d; --muted:#5b6560; --rule:#d8ddd7;
  --accent:#0f5c4d; --tag:#e9bb2f; --tag-ink:#1b1f1d; --warn:#9a5800; --block:#a3261c;
  --display:"Archivo","Arial Narrow",system-ui,sans-serif; --body:"IBM Plex Sans",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#121614; --card:#1a1f1c; --ink:#e7ece8; --muted:#9aa59f; --rule:#2b322e;
  --accent:#62c4aa; --tag:#e9bb2f; --tag-ink:#1b1f1d; --warn:#e3a453; --block:#f07a6e; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#121614; --card:#1a1f1c; --ink:#e7ece8; --muted:#9aa59f; --rule:#2b322e;
  --accent:#62c4aa; --tag:#e9bb2f; --tag-ink:#1b1f1d; --warn:#e3a453; --block:#f07a6e; color-scheme:dark}
body{background:var(--paper);color:var(--ink);font:15px/1.55 var(--body)}
.wrap{max-width:980px;margin:0 auto;padding-block:32px 64px;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  display:flex;flex-direction:column;gap:40px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0}
h1{font-size:clamp(28px,5vw,44px);font-weight:800;letter-spacing:-.01em}
h2{font-size:24px;font-weight:700;display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
h2 small{font:500 12px var(--mono);color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
h3{font-size:18px;font-weight:700}
header{display:flex;flex-direction:column;gap:12px;border-bottom:2px solid var(--ink);padding-bottom:20px}
.meta{font:12px/1.6 var(--mono);color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 18px}
.summary{font-size:17px;max-width:68ch;margin:0}
.total{font:600 14px var(--mono)}
section{display:flex;flex-direction:column;gap:16px}
.verdict{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px 28px;max-width:100%}
.verdict p{margin:0;min-width:0}
.verdict b{font:600 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;display:block;color:var(--muted)}
.picks{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.pick{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:16px;display:flex;flex-direction:column;gap:6px;min-width:0}
.role{font:600 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.where{margin:0;color:var(--muted);font-size:13px}
.landed{margin:4px 0 0;display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:13px}
.num{font:600 22px var(--mono);color:var(--ink);font-variant-numeric:tabular-nums}
.tag{background:var(--tag);color:var(--tag-ink);font:700 12px var(--mono);padding:2px 8px 2px 14px;
  clip-path:polygon(8px 0,100% 0,100% 100%,8px 100%,0 50%)}
.code{font:600 12px var(--mono);border:1px dashed var(--muted);padding:0 6px;border-radius:3px}
.notes{margin:4px 0 0;padding-left:18px;color:var(--warn);font-size:13px}
.pick a,footer a{color:var(--accent);font-weight:600;font-size:13px;margin-top:auto}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th{font:600 11px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);text-align:left}
th,td{padding:7px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
td.r,th.r{text-align:right;white-space:nowrap}
tr.blocked td{color:var(--muted)} tr.blocked td:last-child{color:var(--block)}
details{border-top:1px solid var(--rule);padding-top:8px} summary{cursor:pointer;color:var(--muted);font-size:13px}
.checks ul{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px;max-width:80ch}
.checks{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:16px 20px}
.checks h2{font-size:18px}
.fine{font-size:12px;color:var(--muted);margin:0;max-width:90ch}
.pick:first-child .role{color:var(--ink)}
footer{border-top:2px solid var(--ink);padding-top:16px;color:var(--muted);font-size:13px;display:flex;flex-direction:column;gap:8px}
footer p{margin:0;max-width:75ch}
@media (prefers-reduced-motion:no-preference){.pick{transition:border-color .15s}.pick:hover{border-color:var(--accent)}}
"""


def render_html(ctx: dict) -> str:
    v, short, by_id = ctx["verdict"], ctx["shortlist"], ctx["offers_by_id"]
    secs = []
    lineup_ref = {r["item"]: (r["pl_30d_low"] or r["pl_now"]) for r in ctx.get("lineup") or []}
    for cat, label in ORDER:
        if cat not in short and cat not in v:
            continue
        cv = v.get(cat) or {}
        refs = {e["item"]: e.get("home_ref_pln") for e in short.get(cat, [])}
        cards = [_card(by_id[oid], role, refs.get(by_id[oid]["item"]) or lineup_ref.get(by_id[oid]["item"]))
                 for oid, role in _roles(cv, cat)]
        items = short.get(cat, [])
        table = _table(items[:25])
        if cat == "vacuum" and ctx.get("lineup"):
            table = _lineup_table(ctx["lineup"], ctx.get("prev", {}))
            items = [r for r in ctx["lineup"] if r["landed"]]
        secs.append(f"""
<section id="{cat}">
  <h2>{escape(label)} <small>{len(items)} items compared</small></h2>
  <div class="verdict"><p><b>Why</b>{escape(cv.get('why', ''))}</p><p><b>Watch out</b>{escape(cv.get('watch_out', '') or '–')}</p></div>
  <div class="picks">{''.join(cards) or '<p>No pick: nothing beats the normal price.</p>'}</div>
  {f'<h3>Every Roborock model, best price first by value</h3>{table}' if cat == 'vacuum' else f'<details><summary>Show the comparison table</summary>{table}</details>'}
</section>""")
    fx = ctx["fx"]
    checks = "".join(f"<li>{escape(n)}</li>" for n in ctx.get("checks") or [])
    checks = f'<section class="checks"><h2>Checks before you buy</h2><ul>{checks}</ul></section>' if checks else ""
    return f"""<title>Black Friday Scout</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=IBM+Plex+Mono:wght@500;600;700&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <h1>Black Friday Scout</h1>
  <p class="summary">{escape(v.get('summary', ''))}</p>
  <p class="total">Suggested spend: {money(v.get('total_spend_pln'))}</p>
  <div class="meta"><span>Run {escape(ctx['run_at'])}</span><span>FX: NBP table {escape(fx['table'])} · EUR {fx['rates']['EUR']:.4f} · GBP {fx['rates']['GBP']:.4f} · USD {fx['rates']['USD']:.4f}</span>
  <span>{ctx['n_offers']} offers from {escape(', '.join(ctx['sources']))}</span><span>Verdict: {escape(ctx['model'])}</span></div>
</header>
{checks}
{''.join(secs)}
<footer>
  <p><b>Landed cost</b> = what lands at home in zł. EU shops re-tax at Polish VAT (OSS). UK/US goods add forwarding, 2.2% duty on vacuums, 23% import VAT on goods+freight+duty and a carrier clearance fee; UK VAT is not refunded through a forwarder. Gifts are bought and delivered inside the UK.</p>
  <p>Prices change by the hour on Black Friday. Re-check the price at checkout; deal-site prices can include vouchers or member-only pricing (shown in the notes).</p>
</footer>
</div>
"""


def render_md(ctx: dict) -> str:
    v, by_id = ctx["verdict"], ctx["offers_by_id"]
    lines = [f"# Black Friday Scout ({ctx['scraped']})", "", v.get("summary", ""), "",
             f"Suggested spend: {money(v.get('total_spend_pln'))}", ""]
    if ctx.get("checks"):
        lines += ["## Checks before you buy", ""] + [f"- {n}" for n in ctx["checks"]] + [""]
    for cat, label in ORDER:
        cv = v.get(cat)
        if not cv:
            continue
        lines += [f"## {label}", "", f"**Why:** {cv.get('why', '')}", f"**Watch out:** {cv.get('watch_out', '')}", ""]
        for oid in _ids(cv):
            o = by_id[oid]
            lines.append(f"- {o['item']} — {o['retailer']} ({o['market']}) {money(o['price'], o['currency'])} → "
                         f"**{money(o['landed'])} landed** {o.get('url') or ''}")
        lines.append("")
    return "\n".join(lines)
