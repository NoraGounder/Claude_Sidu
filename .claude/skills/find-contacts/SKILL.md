---
name: find-contacts
description: Run Layer 3 of the Quailworks lead engine. Finds decision-makers at Tier 1-3 accounts with FullEnrich people search, ranks them with TypeSafe Jev 1.14 (job titles only), and finds work emails for the chosen contacts with FullEnrich. Use when asked to find contacts, people, decision-makers or emails.
---

# Layer 3: contacts and work emails

Paid: FullEnrich (about $0.055 per credit; 0.25 credit per person returned, 1 credit per email found,
nothing when not found) and Jev 1.14 (fractions of a cent). Caps in `clients/<client>/limits.yaml`.

1. Dry run: `python -m gtm --client <client> contacts --dry-run`. It shows which accounts are next
   (Tier 1 first, then by signal) and the search cost.
2. Small live test first: `contacts --limit 10`. Check the `contacts` table: are the people the right
   roles at the right company? Are Jev's relevance scores sensible? How many emails came back, and
   with what status?
3. Then the full run: `contacts` (people search, selection, emails), or in two steps with
   `--skip-emails` and later `--emails-only`.

How selection works
- FullEnrich returns up to `--search-limit` people per company matching the persona titles in icp.yaml.
- Python drops junior titles, people without a full name, and owner-director titles at companies over
  150 employees.
- Jev 1.14 rates each remaining job title for buying relevance (titles only, never names). The best
  `max_contacts` per tier (scoring.yaml `enrichment_policy`) with relevance of at least 0.5 are selected.
- Emails: DELIVERABLE or HIGH_PROBABILITY are accepted; CATCH_ALL is kept and marked, and Layer 4
  decides; anything else is "no_email".

Rules
- Contacts are personal data: they stay in `data/` (gitignored). Never print lists of names or emails
  in chat beyond a few examples, and never commit them.
- Every contact stores where its data came from (`data_source`), for the GDPR notice in the first email.
- Jev failures stop the run. Never use another model. Never raise a budget cap yourself.
- Keys: `FULLENRICH_API_KEY` and `OPENROUTER_API_KEY`. In a cloud session, set both to `proxy-injected`;
  the real keys are network secrets for app.fullenrich.com and openrouter.ai.
