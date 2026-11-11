# Quailworks: launch plan for its own outbound (2026-11-10)

Objective: the most booked sales calls per dollar (decisions.md). Measured weekly in positive replies,
booked working sessions and cost per booked call, not emails sent. Set-up and the first runs happen in
parallel; only Tier 1-2 is emailed.

## This week, in parallel

**The user** (decisions.md Q18-Q26):
- buys three Quailworks brand domains and six fresh SmartSenders mailboxes in the founder's name in
  the existing Smartlead account, with warm-up on from day one (campaigns `QW`). Warm-up takes
  2-3 weeks: first sends about 1-3 December 2026;
- moves Apify to Starter and tops up FullEnrich;
- changes the LinkedIn headline to Quailworks, makes a Google Calendar booking page, writes to the
  20-30 people on the warm list, and OKs the website section.

**Quailworks runs** (Apify, FullEnrich and OpenRouter keys are injected in the cloud session):

```bash
python -m gtm --client quailworks discover --dry-run     # 8 searches, US + UK, 2,400 companies, about $9.60
python -m gtm --client quailworks discover
python -m gtm --client quailworks prefilter              # crawl and rules (free)
python -m gtm --client quailworks jev                    # Jev 1.14 decisions, about $0.30
python -m gtm --client quailworks tiers --tier tier_1 --verbose   # calibrate on the first 20 (scoring.yaml)
python -m gtm --client quailworks contacts --dry-run     # Tier 1-2 only, within the $40 FullEnrich cap
python -m gtm --client quailworks contacts
python -m gtm --client quailworks gate
python -m gtm --client quailworks draft && python -m gtm --client quailworks approve
```

Drafts stay previews until `private/sender.yaml` exists; the founder sees them before the "go".

## Sending (after warm-up and the user's "go")

- **Who:** Tier 1 (hiring sales roles now) first, then Tier 2; US and UK in parallel, each in its own
  working hours. Up to 2 contacts per company, one at a time.
- **Ramp:** week 1: 5 a day per mailbox (30 a day); week 2: 10 (60); week 3 on: 15 (90). Each step only
  with bounces under 2% and no spam complaints. Monday to Thursday. Layer 6 runs on the user's laptop
  (Smartlead's key goes in the URL).
- **Second touch:** a LinkedIn connection request from the founder to Tier 1 contacts the day after
  email 1 (by hand, about 5 a day).
- **Replies:** forwarded to the founder; interested replies answered within one working hour with the
  booking link (`templates/replies.yaml`); then `sync` and `handoff` for briefs and outcomes.

## Rough funnel (estimates to replace with real numbers after week 2)

| Step | Estimate | Basis |
|---|---|---|
| Companies found | about 2,400 | 8 searches x 300 |
| Tier 1-2 | about 300-350 | about 15% reached Tier 1-2 in The Marble Jar's run |
| Contacts emailed | about 500 | up to 2 per company |
| Positive replies | about 10-25 | 2-5% of people emailed, signal-based and fact-based |
| Booked calls | about 7-18 | about 70% of positive replies with a one-hour answer |

## Every week: scale what books calls

`learn` per market, segment, signal and opening (decisions.md Q27):
- after 100 contacts in a segment or market: under 1 positive reply, change the opening or drop it;
  3% or more, give it the volume;
- a signal or opening that clearly works gets more weight (`scoring.yaml`, `hook_priority`);
- Tier 3 and the phase 2 segments only once Tier 1-2 is used up and the message works.

## Monthly cost (public list prices, USD)

| Item | Plan | Per month |
|---|---|---|
| Smartlead | the existing Pro account (shared with The Marble Jar's campaigns, separate domains and mailboxes) | 0 extra |
| Mailboxes | 6 fresh SmartSenders mailboxes on 3 brand domains | about 27 |
| Domains | 3 sending domains (about $13 a year each) | about 3 |
| Apify | Starter (shared with The Marble Jar); back to free in months without discovery | about 19 |
| FullEnrich | top-up for the shared account; Quailworks capped at $40 | up to 40 |
| TypeSafe Jev 1.14 | per request | under 3 |
| HubSpot | own free portal, once meetings exist | 0 |
| **Total new spend** | | **about 70-90** |

At the funnel above that is roughly $5-15 per booked call in the first month.
