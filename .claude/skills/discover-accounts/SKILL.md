---
name: discover-accounts
description: Run Layer 1 of the Quailworks lead engine. Finds target companies for a client with Harvest API's LinkedIn company search on Apify, filters and dedupes them, and stores them in data/engine.db. Use when asked to find, source or refresh target accounts.
---

# Layer 1: discover accounts

1. Read `clients/<client>/icp.yaml` and confirm the segments you will run are the ones the user wants.
2. Always start with a dry run. It shows each search and its cost, and calls nothing:
   `python -m gtm --client <client> discover --dry-run`
3. For a first run, or a new segment, test small and look at the raw data before running the full search:
   `python -m gtm --client <client> discover --segment <name> --max-items 25`
   Then check `python -m gtm --client <client> stats` and a few rows in `data/engine.db`. Confirm:
   - companies are the right country and sector
   - employee counts and websites came through. If they are empty, check `raw_json` and update `normalise()` in `engine/gtm/layers/l1_discover.py`.
   - the company-size filter was applied. If sizes are off, fix `linkedin_company_sizes` in icp.yaml.
4. Full run: `python -m gtm --client <client> discover` (all enabled segments). Run it once a month:
   each segment continues from the page where the last run stopped, and the $5 Apify cap matches
   Apify's free monthly credit. Full mode (the default) is needed: short mode has no website, size or HQ.
   LinkedIn's location filter matches any office, so the engine keeps only companies whose
   headquarters is in an allowed country.
5. Report to the user: fetched, new, duplicates, qualified and rejected (with reasons), plus spend against the monthly cap.

Rules
- Never raise a budget cap in `limits.yaml` yourself. If the guard stops a run, tell the user the numbers.
- Never commit anything from `data/` or `clients/<client>/private/`. The repo is public.
- Needs `APIFY_TOKEN`. In a cloud session, `api.apify.com` must be allowed and the token saved as a network secret.
