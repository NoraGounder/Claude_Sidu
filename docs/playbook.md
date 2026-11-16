# Quailworks outbound playbook

What one full set-up taught us, with numbers. Counts and costs only: no prospect names (public repo).
Start a new client with the `new-client` skill and `clients/_template/`.

## Quailworks' own launch (US and UK, companies selling to engineering teams), 2026-11-10 to 11-16

| Step | Count | Note |
|---|---|---|
| Companies found (LinkedIn search, BlitzAPI by hiring signal) | 2,987 | |
| Passed size, country and exclusion filters | 2,595 | |
| Tier 1-2 after crawl, rules and Jev decisions | 194 | 7% of found: the filter is the product |
| Decision-makers chosen | 270 | max 2 per company |
| Work emails found | 245 | BlitzAPI first, FullEnrich fallback |
| Verified and passed the send gate | 181-217 | grows as held contacts clear |

Data and AI spend for all of it: **about $40** (Apify $12.89, FullEnrich $25.64, MillionVerifier $1.16,
OpenRouter $0.27): **$0.21 per Tier 1-2 company, $0.22 per verified contact.** Jev 1.14 decisions cost about
$0.00002 each. Flat monthly tools: BlitzAPI Start $99, mailboxes about $27, domains about $2, Smartlead shared.

Replies, meetings and revenue: filled in after the launch (`funnel`, `learn`).

## What moved quality most

1. **Hiring signals from the company's own job board** (Greenhouse, Lever, Ashby public feeds) instead of
   guessing from the careers page: exact titles, dated, quotable.
2. **Jev checks every job-ad match** before it can be quoted: no "I saw you're hiring" on a stale page.
3. **Three named companies in the prospect's market that are hiring** (email 1): concrete, checkable,
   and it shows the product. Never name vendors, recruiters or the prospect itself.
4. **A no-call ask**: "Shall I send you 10 companies with a buying signal right now?"
5. **Verify everything** before fresh mailboxes send; in a sample, 2 of 7 "deliverable" results disagreed with a
   second check.

## Tools, by value for money (November 2026)

| Need | Use | Instead of |
|---|---|---|
| Companies by hiring signal, work emails | BlitzAPI (flat plan) | LinkedIn job scraping |
| Companies by industry | Harvest API on Apify | |
| People search, email fallback | FullEnrich | |
| Email verification | MillionVerifier (prepaid) | finder ratings alone |
| Every AI decision | TypeSafe Jev 1.14 only | |
| Sending | Smartlead, one account, domains per client | an account per client |
| CRM | HubSpot free, one portal per client | |
