# Quailworks: launch plan for its own outbound (2026-11-10)

Goal: the first paying clients for Quailworks after The Marble Jar, at the lowest cost. Measured in
conversations, calls and won engagements, not emails sent. Narrow before volume: the best tier first.

## Phase 0: sending set-up (10-30 November 2026)

- The user buys two sending domains and four SmartSenders mailboxes in the founder's name
  (decisions.md Q18). Fresh mailboxes ($4.50 a month) warm up for 2-3 weeks while discovery waits
  for December's Apify credit, so nothing waits on warm-up.
- Link the mailboxes to the existing Smartlead account with warm-up on. Campaigns use the `QW` prefix.
- Already excluded: Quailworks, The Marble Jar (`icp.yaml`, `private/exclusions.csv`).

## Phase 1: first leads (from 1 December 2026)

```bash
python -m gtm --client quailworks discover --dry-run     # 3 segments, 900 companies, about $3.60
python -m gtm --client quailworks discover
python -m gtm --client quailworks prefilter              # crawl and rules (free)
python -m gtm --client quailworks jev                    # Jev 1.14 decisions, about $0.10
python -m gtm --client quailworks tiers --tier tier_1 --verbose   # Quailworks calibrates on the first 20 (scoring.yaml)
python -m gtm --client quailworks contacts --dry-run     # Tier 1-2 only, within the $20 FullEnrich cap
python -m gtm --client quailworks contacts
python -m gtm --client quailworks gate
python -m gtm --client quailworks draft && python -m gtm --client quailworks approve
```

## Phase 2: narrow outbound (from about 3 December 2026, after the user's "go")

- **Who:** Tier 1 (hiring sales roles now), then Tier 2. Expect roughly 60-100 companies, up to 2 contacts each.
- **Angle:** before that new sales hire starts, where will their first conversations come from?
- **Volume:** at most 20 emails a day, Tuesday to Thursday, US Central time; one contact per company at a time.
- **Parked:** Tier 3 and the phase 2 segments (instruments, machinery).

## Phase 3: scale what works

Weekly `learn`: conversations per signal, opening, tier, persona and segment.

- Fewer than 2 conversations after the first 100 contacts: change the message or the segment, not the volume.
- A signal or opening that clearly works: give it more weight (`scoring.yaml`, `hook_priority`).
- Then: Tier 3, the phase 2 segments, more volume; the UK and Ireland only after the US message works.

## Monthly cost (public list prices, USD)

| Item | Plan | Per month |
|---|---|---|
| Smartlead | the existing Pro account (shared with The Marble Jar's campaigns) | 0 extra |
| Mailboxes | 4 fresh SmartSenders mailboxes on 2 domains | about 18 |
| Domains | 2 sending domains (about $13 a year each) | about 2 |
| FullEnrich | the existing plan's credits, capped at $20 | 0 extra |
| Apify (Harvest API) | free plan credit from December | 0 |
| TypeSafe Jev 1.14 | per request | under 1 |
| HubSpot | own free portal, once meetings exist | 0 |
| **Total new spend** | | **about 20** |
