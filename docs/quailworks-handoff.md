# Handoff: outbound for Quailworks itself

Written 10 November 2026 at the end of the session that built the lead engine for The Marble Jar
(TMJ). Read `CLAUDE.md` first: its hard rules apply to every client, Quailworks included.

## Status (10 November 2026, later the same day)

Done: `clients/quailworks/` exists and its decisions are recorded in `clients/quailworks/decisions.md`
(US companies with 11-200 employees that sell to manufacturers and industrial operators; lead offer:
done-for-you outbound). The engine's The Marble Jar-specific prompts, signal rules and copy logic are
now per-client settings with The Marble Jar's behaviour as the default (CLAUDE.md, "Client-specific
behaviour lives in config"); 74 tests. Next: the user buys two sending domains and four mailboxes
(warm-up through November), then the first discovery run on or after 1 December 2026, when Apify's
free credit resets (`clients/quailworks/launch-plan.md`).

## What already exists (reuse it, do not rebuild)

The engine in `engine/gtm/` is client-agnostic. Every client is a folder under `clients/<client>/`
and every command takes `--client <slug>`. A new client = a new folder with these files, copied from
`clients/the-marble-jar/` and rewritten:

| File | What to change for Quailworks |
|---|---|
| `client.yaml` | identity, sender (the founder of Quailworks), language |
| `offer.md`, `brain.yaml`, `decisions.md` | Quailworks' offer, buyers, pains, voice; decide, record why |
| `icp.yaml` | segments (LinkedIn industry IDs, sizes, countries), personas, exclusions |
| `scoring.yaml` | fit and buying-signal weights, tiers |
| `templates/sequence.yaml`, `templates/replies.yaml` | the 4-step sequence and first answers |
| `gate.yaml` | GDPR notice with Quailworks' own address |
| `sending.yaml`, `limits.yaml`, `ai.yaml` | regions, caps, budgets; keep the Jev 1.14-only policy |
| `private/` (gitignored) | `sender.yaml`, `exclusions.csv` (current clients, TMJ included) |

Layers: 0 config and brain → 1 discover (Harvest API on Apify) → 2 crawl, rules, Jev 1.14 scoring
and tiers → 3 FullEnrich people and emails → 4 send gate → 5 drafts, Jev fact check, `approve` →
6 Smartlead upload, start, sync → 7 handoff briefs, outcomes, learning, HubSpot mirror. 66 tests
(74 with the Quailworks client).

## Quailworks facts (public registers, checked 9 November 2026)

- Quailworks sp. z o.o., ul. Mikołaja Reja 34, 26-225 Gowarczów, Poland. KRS 0001108506,
  NIP 6582000945, REGON 528769513. Each management board member may represent alone; the
  President of the Management Board is Sidarth Thrumurthy.
- Website quailworks.xyz (this repo's `index.html`): AI automation agency, est. 2025. Services:
  outbound automation, workflow automation (Make, Zapier, custom APIs), custom AI agents.
  Approach: diagnose, design, build, hand off. Project-based or retained.
- Proof so far: one client (The Marble Jar), launching late November 2026. No results yet.

## Hard boundaries for the Quailworks campaign

1. **Never reuse The Marble Jar's prospect data** (accounts, contacts, replies in `data/`) for
   Quailworks. The DPA with TMJ (article 8.4) forbids using it for any other purpose or client, and
   GDPR purpose limitation says the same. Quailworks finds its own prospects with its own runs.
2. **Separate sending infrastructure.** Quailworks sends from its own domains and mailboxes, never from
   TMJ's sending domains. Own Smartlead campaigns (`campaign_prefix` in
   `sending.yaml`).
3. **Separate budgets.** Apify's free $5 credit is shared by the account and TMJ used $4.80 of it in
   November 2026: Quailworks discovery needs the next month or a paid Apify plan (ask the user before
   raising any cap). FullEnrich credits are shared too (about 770 left after TMJ's run).
4. Put TMJ in Quailworks' `private/exclusions.csv`: a client is never prospected.

## Decisions and lessons from the TMJ build (apply them)

- **Tools chosen for price/performance:** Harvest API on Apify (not Sales Navigator), requests +
  Crawl4AI, TypeSafe Jev 1.14 via OpenRouter Decisions API (the only AI for decisions), FullEnrich
  (waterfall, no second provider), MillionVerifier only for stale re-checks, Smartlead Pro (API and
  webhooks start at Pro, $94/month), SmartSenders mailboxes ($4.50/month each, $13/year per domain),
  HubSpot free only once meetings exist. Rejected: Pancake (DMs only, no email, startup-shaped data,
  conflicts with the Jev-only rule), LeadMagic ($99/month minimum), Clay, Exa (not needed yet).
- **Narrow before volume:** start with the best tier only (TMJ: 124 companies, 40 emails a day,
  4-6 mailboxes). Scale only what `learn` shows produces conversations and revenue.
- **Signals beat fit:** hiring for the work you replace is the strongest signal (TMJ: admin job ads).
  For Quailworks, think: companies hiring SDRs/BDRs or ops/admin roles, posting about manual
  processes, or using Make/Zapier/HubSpot (tech-stack signals).
- **Copy rules:** human-written templates, facts only from crawled pages with a source, openings as
  questions that presume nothing, no claims about timelines, prices, integrations or free work unless
  confirmed. Jev's fact check flags presumptive openings; a flagged opening falls back automatically.
- **Sending domains:** brand variants of the sender's own company, mailboxes in the real sender's
  name. Never generic pre-warmed domains with made-up personas (deceptive, hurts replies, breaks
  Dutch/EU sender-identity rules). Fresh mailboxes need 2-3 weeks of warm-up.
- **GDPR:** a DPA is required when processing personal data for a client (Article 28(9): in writing,
  an email "agreed" counts). For Quailworks' own outreach Quailworks is the controller itself, so no
  DPA is needed, but the first email must carry the source of the data, an opt-out and the postal
  address, and suppression must be honoured (`retention` deletes data on schedule).
- **Smartlead's API key goes in the URL**, so Layer 6 runs on the user's laptop with `.env`; a cloud
  session can only proxy header-based keys (Apify, OpenRouter, FullEnrich, HubSpot).
- **FullEnrich:** rate limits (429) are retried; slow bulk batches (up to ~4 hours) are recorded as
  `pending` and collected later, never bought twice.
- **Do not ask the client; decide** (CLAUDE.md rule 8). For Quailworks the user is the client, so
  decide from quailworks.xyz and record decisions in `clients/quailworks/decisions.md`.

## The Marble Jar status (do not disturb)

133 contacts at 88 Dutch companies have approved drafts in `data/engine.db` (client
`the-marble-jar`). Mailboxes on two brand domains are warming up; launch planned for about
23-30 November 2026 after the user's explicit "go". Leave that client's data and config alone.
