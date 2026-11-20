---
name: eta-search
description: Run the ETA search (clients/eta), Sidarth's own search for a UK business to buy. Finds companies on the Companies House register by SIC code and age, reads their profile, filed accounts (iXBRL) and owners, screens them on public numbers (sieve 1), keeps an evidence ledger, and writes a ranked shortlist. Use when asked to find, screen or rank businesses to acquire.
---

# ETA search, milestone 1: registry sourcing and sieve 1

1. Read `clients/eta/eta.yaml` (buy box, SIC codes, sieve-1 bars) and `clients/eta/decisions.md`.
2. Dry run first: `python -m gtm --client eta eta-discover --dry-run`.
3. Small live run on one code: `python -m gtm --client eta eta-run --code 71200 --max-per-code 50 --limit 50`.
   Check `eta-stats`, a few rows in the CSV in `data/eta/`, and `eta-evidence <number>` for the top company.
4. Sieve 2 on the survivors: `python -m gtm --client eta eta-qualify --dry-run`, then `--limit 25`. It scores each
   SIC code on Stanford's industry scorecard and each company on Hamilton Helmer's 7 Powers (Jev 1.14 only).
5. Then widen: more codes, higher `--max-per-code`. Each run continues where the last stopped.
6. Report: found, dropped (with reasons), pass/review/fail, the top 10 with score, owner age and size.

Rules
- Free API, 600 requests per 5 minutes; the client paces itself and stops at `limits.yaml` `max_requests_per_run`.
- Owner names and birth dates are personal data: they stay in `data/` (gitignored). Never commit them or put them in Notion.
- Bars in eta.yaml are Sidarth's to set; change them only on his say-so and record it in decisions.md.
- No outreach from this client until the next milestone and Sidarth's explicit go.
