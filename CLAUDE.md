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
6. **AI decisions use TypeSafe Jev 1.14 only.** Model `typesafe/jev-1.14` through
   `https://openrouter.ai/api/alpha/decisions`, authenticated with `OPENROUTER_API_KEY`. Never OpenRouter
   Auto Router, Jev Router, the Jev Latest alias, or GPT, Claude, Gemini or any other model through
   OpenRouter, and no fallback: if Jev is unavailable, stop and report the error. Jev does qualification,
   ICP scoring and classification; crawling, deterministic checks and data processing stay in Python.
   Every request logs the reported model ID, tokens and cost (table `jev_calls`). Never print or store
   the API key. The policy lives in `clients/<client>/ai.yaml` and is enforced by `gtm/sources/jev.py`.
7. **The Marble Jar (2026-11-06):** Mendix is not offered and never appears in outreach. Market: English-speaking
   clients, US + UK + Ireland first. The main offer is NOT confirmed: ICP, scoring and copy are provisional and all
   Layer 1 segments stay switched off until Mithun answers `clients/the-marble-jar/open-questions.md`. Do not assume
   integrations or other services have stopped, do not assume the November 2026 platform is pebls, and do not change
   website positioning (the website refresh is a separate project).

## The pipeline

| Layer | What it does | Tools | Code | Status |
|---|---|---|---|---|
| 0 | Offer, ICP, qualification rules, budgets | config files | `clients/<client>/` | built |
| 1 | Discover target accounts | Harvest API (Apify) | `gtm/layers/l1_discover.py` | built |
| 2 | Cheap pre-filter: crawl site and careers pages, deterministic rules, Jev 1.14 decisions (non-buyers, ICP fit, admin job titles), score and tier | requests + BeautifulSoup, Crawl4AI browser for blocked and JavaScript pages, TypeSafe Jev 1.14 | `gtm/layers/l2_prefilter.py`, `l2_jev.py` | built |
| 3 | Find decision-makers (FullEnrich people search), rank them with Jev 1.14 (titles only), find work emails for the chosen ones (max 2 per Tier 1–2 account, 1 for Tier 3) | FullEnrich, TypeSafe Jev 1.14 | `gtm/layers/l3_contacts.py` | built |
| 4 | Send gate: suppression, role/free-mail addresses, domain match, contact country, email status, catch-all cap, freshness, sender consent, GDPR source | Python rules (`gate.yaml`); MillionVerifier only to re-check stale emails | `gtm/layers/l4_gate.py` | built |
| 5 | Drafts from human-written templates and crawled facts only; Jev 1.14 picks the angle and fact-checks the opening; Quailworks reviews in Google Sheets | Python templates, TypeSafe Jev 1.14, CSV round-trip | `gtm/layers/l5_copy.py` | built |
| 6 | Sending and reply handling | Smartlead + SmartSenders mailboxes | — | planned |
| 7 | Handoff, CRM and learning | HubSpot (free), meeting brief to client | — | planned |

## How to run

```bash
cd engine && pip install -e ".[dev]"
python -m gtm --client the-marble-jar discover --dry-run          # shows queries and cost estimate
python -m gtm --client the-marble-jar discover --segment logistics_nl --max-items 50
python -m gtm --client the-marble-jar stats
python -m gtm --client the-marble-jar export --status qualified_l1
python -m gtm --client the-marble-jar prefilter --limit 20     # Layer 2 trial (free)
python -m gtm --client the-marble-jar tiers --tier tier_1 --verbose
python -m gtm --client the-marble-jar jev --dry-run            # Jev 1.14 decisions (shows first request)
python -m gtm --client the-marble-jar jev                      # decide all scored accounts
python -m gtm --client the-marble-jar contacts --dry-run       # Layer 3 plan and cost
python -m gtm --client the-marble-jar contacts --limit 10      # Layer 3 small live test
python -m gtm --client the-marble-jar gate                     # Layer 4 send gate (free)
python -m gtm --client the-marble-jar draft && python -m gtm --client the-marble-jar export-drafts   # Layer 5
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
- `clients/<client>/ai.yaml`: AI policy (Jev 1.14 only, no fallback) and decision thresholds
- `clients/<client>/gate.yaml`: Layer 4 send-gate rules and the GDPR notice text
- `clients/<client>/private/exclusions.csv`: real do-not-contact list (gitignored)
- `engine/gtm/`: the engine; `engine/tests/`: tests with synthetic data only
- `.claude/skills/`: one skill per runnable layer
