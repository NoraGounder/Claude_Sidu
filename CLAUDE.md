# Quailworks lead engine: operating manual for Claude Code

Quailworks is a done-for-you outbound agency. Claude Code is the architect and the operator of
the lead engine: it builds every layer, runs them, and connects every outside tool by API, CLI
or MCP. A client only takes the meetings we book.

The repository also hosts the agency website (`index.html`). Leave it alone unless asked.

## Hard rules

1. **This repository is public.** Never commit prospect data, contact details, client-private
   files, exports or API keys. Pipeline data lives in `data/` and client-private files in
   `clients/<client>/private/`. Both are gitignored. Check `git status` before every commit.
2. **Money:** every paid call goes through the budget guard (`gtm.budget`) and is logged in the
   `runs` table. Do a `--dry-run` before any new kind of paid run, and respect
   `clients/<client>/limits.yaml`. Never raise a cap without the user's say-so.
3. **No sending, no CRM writes, no deletes on outside systems** without explicit approval from
   the user in this conversation. These are Layers 6 and 7, and they will have their own gates.
4. **Compliance (NL/BE, GDPR):** check suppression before enrichment and before sending. Record
   the data source on every contact. Never scrape behind a login. Respect robots.txt when crawling.
5. Keep systems simple. If a layer needs a manual step from the client, it is wrong.

## The pipeline

| Layer | What it does | Tools | Code | Status |
|---|---|---|---|---|
| 0 | Offer, ICP, qualification rules, budgets | config files | `clients/<client>/` | built |
| 1 | Discover target accounts | Harvest API (Apify) | `gtm/layers/l1_discover.py` | built |
| 2 | Cheap pre-filter: crawl site and careers pages, rules, AI for unclear cases, score and tier | Crawl4AI, Python, Jev | — | next |
| 3 | Find decision-makers and work emails (max 2 per account, stop on first hit) | Harvest API, LeadMagic, FullEnrich (Tier 1–2 misses only) | — | planned |
| 4 | Quality and permission gates | MillionVerifier, suppression, GDPR rules | — | planned |
| 5 | Personalisation and QA | Claude, Google Sheets review by Quailworks | — | planned |
| 6 | Sending and reply handling | Smartlead + SmartSenders mailboxes | — | planned |
| 7 | Handoff, CRM and learning | HubSpot (free), meeting brief to client | — | planned |

## How to run

```bash
cd engine && pip install -e ".[dev]"
python -m gtm --client the-marble-jar discover --dry-run          # shows queries and cost estimate
python -m gtm --client the-marble-jar discover --segment logistics_nl --max-items 50
python -m gtm --client the-marble-jar stats
python -m gtm --client the-marble-jar export --status qualified_l1
pytest -q
```

Run the paid layers from a machine with open internet access, such as the user's laptop. In a
Claude Code cloud session, each vendor's host must be allowed and its key saved as a network
secret. See `.env.example`.

## Where things live

- `clients/<client>/client.yaml`: identity, sender, language, approvals still pending
- `clients/<client>/offer.md`: the offer and the definition of a qualified meeting
- `clients/<client>/icp.yaml`: segments for Layer 1, personas for Layer 3, hard exclusions
- `clients/<client>/scoring.yaml`: fit and signal scoring for Layer 2
- `clients/<client>/limits.yaml`: monthly budget caps and send caps
- `clients/<client>/private/exclusions.csv`: real do-not-contact list (gitignored)
- `engine/gtm/`: the engine; `engine/tests/`: tests with synthetic data only
- `.claude/skills/`: one skill per runnable layer
