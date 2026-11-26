# bf-deals: Black Friday deal scout

Finds the best price for a shopping list across Poland, the EU, the UK and the US,
prices every offer **landed at home** (VAT, customs, forwarding), and asks
[Jev Router](https://openrouter.ai/typesafe/jev-router) on OpenRouter to pick.

```
sources.yaml ──► 1 scrape ──► data/raw/*.json ──► 2 normalize ──► 3 landed cost ──► 4 rank ──► 5 report
                 (Firecrawl MCP:                   one offer      NBP FX, VAT,      shortlist   data/out/
                  Alexandria +                     schema         duty, forwarder   + Jev       report.html
                  scrape + search)                                                  verdict     report.md
```

| Stage | Where | What it does |
|---|---|---|
| 1 Scrape | Claude Code + Firecrawl MCP, driven by `sources.yaml` | Deal communities (mydealz DE, hotukdeals UK, Slickdeals US), Tweakers NL, Amazon US via Alexandria; Ceneo PL, Amazon UK and the Amazon.de wishlist via `firecrawl_scrape`; vendor pricing via `firecrawl_search`. |
| 2 Normalize | `bfdeals/normalize.py` | One offer schema; classifies titles into items (e.g. `Roborock Saros Z70`); drops stale posts, bundles and noise; flags VPN-region tricks, student-only, personalised and in-store offers. |
| 3 Landed cost | `bfdeals/landed.py` | NBP mid rates. EU shops re-taxed at Polish VAT (OSS). UK/US: forwarder + duty + 23 % import VAT + clearance fee. Gifts priced inside the recipient's country. Blocks US vacuums (120 V, no EU warranty). |
| 4 Rank | `bfdeals/rank.py` | Deterministic shortlist per item vs the Polish reference price, then one Jev Router call. The model may only cite shortlisted offer ids; unknown ids are dropped. Falls back to cheapest-landed picks if the call fails. |
| 5 Report | `bfdeals/report.py` | Artifact-ready HTML (light/dark, phone width) and Markdown. |

## Run

```bash
pip install pyyaml
cp config.example.yaml config.local.yaml   # set wishlist_url, gift_delivery, recipient_age, optional budget
python run.py                               # needs OpenRouter access (OPENROUTER_API_KEY or a proxy)
python run.py --no-llm                      # deterministic picks only
python run.py --reuse-verdict               # re-render without a new model call
```

To refresh prices, ask Claude Code to "re-run stage 1 of tools/bf-deals from sources.yaml";
it saves the raw results into `data/raw/`, then run `python run.py`.

## Cost per run (26 Nov 2026)

- Firecrawl: about 190 credits for the full scrape (Alexandria calls 5 credits each; wishlist pages 5 each).
- Jev Router: about $0.01 per verdict (it routed to `deepseek-v4.1-flash`, ~17k in / ~11k out tokens).
  Jev's reasoning tokens share `max_tokens` with the answer, so keep `reasoning_effort: low`
  or the reply can come back empty (`finish_reason=length`).

## Privacy

`data/` (raw scrapes, wishlist, report) and `config.local.yaml` are gitignored. This repo is
public: keep names, addresses and wishlist contents out of committed files.
