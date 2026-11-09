# The Marble Jar: launch plan (2026-11-09)

Goal: new paying clients for The Marble Jar at the lowest cost. Measured in conversations,
proposals and won revenue, not emails sent. One won project pays for a year of tools, so the
plan optimises for **speed to real conversations with the right companies**, not for volume.

## Phase 0: set up sending (this week)

Quailworks decides; Mithun is not asked questions (`decisions.md`).

- Buy Smartlead Pro ($94; the engine needs its API and webhooks) and 2-3 sending domains with 4-5
  mailboxes through SmartSenders. Pre-warmed mailboxes ($9 instead of $4.50 a month each) skip the
  2-3 week warm-up, so the first emails can go out as soon as the drafts are approved. Keep warm-up on
  and start at 10 a day per mailbox, rising to 15 over the first week.
- Excluded already: every client shown on themarblejar.io and The Marble Jar itself (`private/exclusions.csv`).
- Prepare the data processing agreement (GDPR Art. 28) for Mithun to sign. This and a booking link are
  the only things we need from him, in one message at launch.

## Phase 1: prepare the first leads (week 1)

- Re-score with the brain: `jev --redo` (about $0.10), then `prefilter --rescore` (free).
- Contacts and emails for Tier 1-2 only: `contacts` (about $6), `gate`, `draft`; Quailworks reviews.
- Lookalikes come later from our own won deals (`decisions.md` D10), not from Mithun.

## Phase 2: narrow outbound (weeks 2-8)

- **Who:** Tier 1 (companies hiring admin staff now) first, then Tier 2. About 115 Dutch companies, up to 2 contacts each.
- **Angle:** before you hire another admin, look at automating the work.
- **Volume:** at most 40 emails a day (`limits.yaml`), Tuesday to Thursday, 4-5 warmed mailboxes at
  15 a day or fewer. One contact per company at a time.
- **Parked:** Tier 3 (711 companies with fit but no signal). `scoring.yaml` gives it 0 contacts and
  `sending.yaml` sends only Tier 1-2.

## Phase 3: scale what earns money

Weekly `learn` report: conversations per signal, opening, tier, persona and region.

- Fewer than 2 conversations after the first 100 contacts: change the message or the offer, not the volume.
- A signal or opening that clearly works: give it more weight (`scoring.yaml`, `hook_priority`).
- Only after the Dutch Tier 1-2 results show a working message: add Tier 3, then the US, UK and
  Ireland, then possibly LinkedIn messages to Tier 1 (only if Mithun agrees, since they would use his account).

## Monthly cost (public list prices, USD)

| Item | Plan | Per month |
|---|---|---|
| Smartlead | Pro (needed for the API) | 94 |
| Mailboxes | 4-5 SmartSenders mailboxes on 2-3 domains (pre-warmed $9 each, fresh $4.50) | about 25-45 |
| Domains | 2-3 sending domains | about 3 |
| FullEnrich | Pro, 1,000 credits (the Tier 1-2 launch uses about 300) | 55 |
| Apify (Harvest API) | free plan; no new discovery needed for the launch | 0 |
| TypeSafe Jev 1.14 | per request | under 1 |
| HubSpot | free | 0 |
| **Total** | | **about 175-195** |

The earlier plan (10 mailboxes, 100-120 emails a day, all tiers) was about $200 a month. The
saving is small; the main gain is spending Mithun's name and the sending domains only on the
companies most likely to buy.
