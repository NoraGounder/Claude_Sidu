---
name: prefilter-accounts
description: Run Layer 2 of the Quailworks lead engine. Crawls each Layer 1 account's website and careers page, finds buying signals with rules, scores fit and signals, assigns Tier 1/2/3, and runs the AI review of job titles. Use when asked to qualify, score, tier or pre-filter accounts.
---

# Layer 2: pre-filter, score and tier

Free (no paid APIs), but needs open web access. In a cloud session the environment must allow
general internet access; otherwise run it on a laptop.

1. Trial first: `python -m gtm --client <client> prefilter --limit 20`
   Then look at a few rows (`tiers --tier tier_3 --verbose`). Check that sites were reachable, careers pages
   were found, and job titles look like real titles. Fix rules in `engine/gtm/signals.py` or
   `engine/gtm/crawl.py` if not, and re-run with `--rescore` (pages are cached, so this is fast).
2. Full run: `python -m gtm --client <client> prefilter` (or `--rescore` to redo everything from the cache).
3. AI review. Rules cannot read every job title, and they cannot tell an association from a buyer.
   Default: run it through OpenRouter with TypeSafe's Jev Router (needs OPENROUTER_API_KEY):
   `python -m gtm --client <client> ai-review --dry-run` then `ai-review` (add `--all` to also screen
   every account for non-buyers). Answers are strict JSON, checked against the crawled titles, and
   each call's real cost is logged against the `openrouter` cap. Jev Router picks the model per request,
   so cost varies; check `stats` after the first run and tune the estimate in limits.yaml.
   Manual fallback (Claude Code reviews by hand):
   - Export: `python -m gtm --client <client> review-queue` (add `--all` to also screen every
     account for non-buyers).
   - Read `data/<client>-review-queue.jsonl`. For each account write one JSON line to
     `data/<client>-reviews.jsonl`:
     `{"account_id": 12, "admin_roles": ["<exact title from job_titles>"], "not_a_buyer": false, "reason": ""}`
     - `admin_roles`: only titles copied exactly from that account's `job_titles` that are manual
       administrative work: invoice, accounts payable or receivable, order entry or processing, data entry,
       back office, planning administration. Not drivers, engineers, sales, IT or management roles.
     - `not_a_buyer: true` for associations, unions, media and magazines, schools and training bodies,
       public bodies and port authorities, software or IT companies, consultancies and staffing agencies.
       Give a short reason.
   - Apply: `python -m gtm --client <client> apply-review --file data/<client>-reviews.jsonl --reviewer claude`
4. Report: counts per tier, top Tier 1 accounts with their evidence (`tiers --tier tier_1 --verbose`),
   unreachable sites, and how many the review changed.

Rules
- Every signal must point to a page we crawled (URL plus quote) or an exact job title from it.
  Layer 5 only personalises from these facts.
- The crawler identifies itself, respects robots.txt and waits between requests to the same site.
  Do not lower the delay or ignore robots.txt.
- Never commit `data/`.
