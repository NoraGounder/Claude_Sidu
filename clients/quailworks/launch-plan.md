# Quailworks: launch plan for its own outbound (2026-11-10)

Goal: the first paying clients for Quailworks after The Marble Jar, at the lowest cost. Measured in
conversations, working sessions and won audits, not emails sent. The user asked not to wait, so set-up
and the first runs happen in parallel. Narrow where it counts: only Tier 1-2 is emailed.

## This week, in parallel

**The user buys** (decisions.md Q18, Q20):
- two Quailworks brand sending domains (getquailworks.com, quailworkshq.com or tryquailworks.com) and
  four fresh SmartSenders mailboxes in the founder's name, linked to the existing Smartlead account with
  warm-up on from day one (campaigns prefixed `QW`). Warm-up takes 2-3 weeks, so sending starts in
  early December; everything below runs meanwhile;
- a paid Apify plan (Starter) and a FullEnrich top-up.

**Quailworks runs** (Apify, FullEnrich and OpenRouter keys are injected in the cloud session):

```bash
python -m gtm --client quailworks discover --dry-run     # 5 segments, 1,500 companies, about $6
python -m gtm --client quailworks discover
python -m gtm --client quailworks prefilter              # crawl and rules (free)
python -m gtm --client quailworks jev                    # Jev 1.14 decisions, about $0.15
python -m gtm --client quailworks tiers --tier tier_1 --verbose   # Quailworks calibrates on the first 20 (scoring.yaml)
python -m gtm --client quailworks contacts --dry-run     # Tier 1-2 only, within the $40 FullEnrich cap
python -m gtm --client quailworks contacts
python -m gtm --client quailworks gate
python -m gtm --client quailworks draft && python -m gtm --client quailworks approve
```

Drafts stay previews until `private/sender.yaml` exists; the founder sees them before the "go".

## First sends (after 2-3 weeks of warm-up, early December 2026, and the user's "go")

- **Who:** Tier 1 (hiring sales roles now), then Tier 2. Up to 2 contacts per company, one at a time.
- **Angle:** before that new sales hire starts, where will their first conversations come from? Signed
  by an engineer who sat on the buyer's side.
- **Volume:** start at 5 a day per mailbox (20 a day), up to 10 each (40 a day) after a clean first week
  (bounces under 2%, no spam complaints). Tuesday to Thursday, US Central time. Layer 6 runs on the
  user's laptop (Smartlead's key goes in the URL).
- **Parked:** Tier 3 and the phase 2 segments (precision parts, instruments, machinery).

## Then: scale what works

Weekly `learn`: conversations per signal, opening, tier, persona and segment.

- Fewer than 2 conversations after the first 100 contacts: change the message or the segment, not the volume.
- A signal or opening that clearly works: give it more weight (`scoring.yaml`, `hook_priority`).
- Then Tier 3, the phase 2 segments, more volume; the UK and Ireland once the US message works (Q8).

## Monthly cost (public list prices, USD)

| Item | Plan | Per month |
|---|---|---|
| Smartlead | the existing Pro account (shared with The Marble Jar's campaigns) | 0 extra |
| Mailboxes | 4 fresh SmartSenders mailboxes on 2 brand domains | about 18 |
| Domains | 2 sending domains (about $13 a year each) | about 2 |
| Apify | Starter (shared with The Marble Jar) | about 19 |
| FullEnrich | top-up for the shared account; Quailworks capped at $40 | up to 40 |
| TypeSafe Jev 1.14 | per request | under 3 |
| HubSpot | own free portal, once meetings exist | 0 |
| **Total new spend** | | **about 40-80** |
