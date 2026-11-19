# Quailworks Engineering: launch plan (2026-11-19)

Objective: the most qualified engineering conversations per dollar (decisions.md). Same engine, same tools,
same run order as Quailworks' own outbound (`clients/quailworks/launch-plan.md`); only Tier 1-2 is emailed.

## This week, in parallel

**The user** (decisions.md E2, E6, E9, E10):
- buys one sending domain with three SmartSenders mailboxes in the founder's name in the existing Smartlead
  account, warm-up on (about $15 a month), and adds the domain to `sending.yaml mailbox_domains`. First sends
  14 days later;
- writes to the warm list (20-30 people from past programmes and contract agencies) and puts former employers
  in `private/exclusions.csv`;
- approves the one-page profile and the `/engineering` page on quailworks.co.

**Quailworks runs** (free dry runs first; every paid step within `limits.yaml`):

```bash
python -m gtm --client quailworks-engineering discover-hiring --dry-run   # 7 searches, about 1,200 BlitzAPI records (flat plan)
python -m gtm --client quailworks-engineering discover-hiring
python -m gtm --client quailworks-engineering discover --dry-run          # 6 UK/US industry searches, about $6.40 on Apify
python -m gtm --client quailworks-engineering discover
python -m gtm --client quailworks-engineering discover-hiring --postings  # live design postings onto every account
python -m gtm --client quailworks-engineering prefilter                   # crawl and rules (free)
python -m gtm --client quailworks-engineering jev                         # Jev 1.14 decisions, cents
python -m gtm --client quailworks-engineering tiers --tier tier_1 --verbose   # the founder calibrates on the first 20
python -m gtm --client quailworks-engineering contacts --dry-run          # Tier 1-2 only; BlitzAPI first, FullEnrich fallback
python -m gtm --client quailworks-engineering contacts --limit 10
python -m gtm --client quailworks-engineering contacts
python -m gtm --client quailworks-engineering gate --recheck              # MillionVerifier, every address
python -m gtm --client quailworks-engineering draft && python -m gtm --client quailworks-engineering approve
python -m gtm --client quailworks-engineering funnel
```

Drafts stay previews until `private/sender.yaml` exists and consent is granted; the founder reads five in full.

## Sending (after warm-up and the user's "go")

- **Who:** Tier 1 (hiring a design engineer now) first, then Tier 2; UK in UK hours, US in US Central hours.
  Up to 2 contacts per company, one at a time; companies Quailworks GTM emailed in the last 90 days wait (E12).
- **Ramp:** week 1: 5 a day per mailbox (15 a day); week 2: 10 (30); week 3 on: 15 (45). Monday to Thursday,
  each step only with bounces under 2% and no complaints.
- **Second touch:** LinkedIn connection request to Tier 1 contacts the day after email 1, by hand.
- **Replies:** answered within one working hour (`templates/replies.yaml`), the profile sent the same day;
  then `sync` and `handoff` for briefs and outcomes.

## Every week

```bash
python -m gtm --client quailworks-engineering discover-hiring --postings
python -m gtm --client quailworks-engineering prefilter --rescore
python -m gtm --client quailworks-engineering jev --new-titles
python -m gtm --client quailworks-engineering contacts
python -m gtm --client quailworks-engineering gate --recheck
python -m gtm --client quailworks-engineering draft && python -m gtm --client quailworks-engineering approve
python -m gtm --client quailworks-engineering learn
```

After 100 contacts in a segment or market: under 1 positive reply, change the opening or drop it; 3% or
more, give it the volume.

## Monthly cost

| Item | Plan | Extra per month |
|---|---|---|
| BlitzAPI | Quailworks' flat Start plan, 5,000 of 200,000 records | 0 |
| Smartlead | the existing account, `QWE` campaigns | 0 |
| Mailboxes | 3 SmartSenders mailboxes on 1 new domain | about 15 |
| Apify | Quailworks' existing plan, capped at $15 | up to 15 (about 6 for the first run) |
| FullEnrich | shared credits, fallback only, capped at $20 | up to 20 |
| MillionVerifier | prepaid credits, capped at $5 | up to 5 |
| TypeSafe Jev 1.14 | per request | under 2 |
| HubSpot | Quailworks' own free portal | 0 |
| **Total new spend** | | **about 15 fixed + 10-40 usage** |
