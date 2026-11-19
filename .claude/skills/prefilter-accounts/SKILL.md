---
name: prefilter-accounts
description: Run Layer 2 of the Quailworks lead engine. Crawls each Layer 1 account's website and careers page (HTTP, Crawl4AI browser for blocked or JavaScript pages), finds buying signals with rules, gets TypeSafe Jev 1.14 decisions (non-buyers, ICP fit, admin job titles), scores and assigns Tier 1/2/3. Use when asked to qualify, score, tier or pre-filter accounts.
---

# Layer 2: pre-filter, score and tier

Crawling is free; Jev 1.14 costs about $0.00002 per account. Needs open web access. In a cloud session the environment must allow
general internet access; otherwise run it on a laptop.

1. Trial first: `python -m gtm --client <client> prefilter --limit 20`
   Then look at a few rows (`tiers --tier tier_3 --verbose`). Check that sites were reachable, careers pages
   were found, and job titles look like real titles. Fix rules in `engine/gtm/signals.py` or
   `engine/gtm/crawl.py` if not, and re-run with `--rescore` (pages are cached, so this is fast).
2. Full run: `python -m gtm --client <client> prefilter` (or `--rescore` to redo everything from the cache).
3. Jev 1.14 decisions (the only AI in this layer; see `clients/<client>/ai.yaml`):
   `python -m gtm --client <client> jev --dry-run` shows the first request and the cost estimate, then
   `python -m gtm --client <client> jev` decides every Tier 1-3 account Jev has not decided yet. Per account,
   one request to `typesafe/jev-1.14` at `https://openrouter.ai/api/alpha/decisions` answers: is it a
   non-buyer (noul), how well it fits the ICP (score 0-2), and whether each open job title is manual admin
   work (noul). Answers are stored in `jev_decisions` and folded into every later re-score.
   - Never switch models. If Jev fails, the command stops and says why: report that to the user.
   - Every request is logged in `jev_calls` (model ID reported by the API, tokens, cost).
   - In a cloud session, set `OPENROUTER_API_KEY=proxy-injected`; the real key is a network secret.
4. Report: counts per tier, top Tier 1 accounts with their evidence (`tiers --tier tier_1 --verbose`),
   unreachable sites, and how many the review changed.

Rules
- Every signal must point to a page we crawled (URL plus quote) or an exact job title from it.
  Layer 5 only personalises from these facts.
- The crawler identifies itself, respects robots.txt and waits between requests to the same site.
  Do not lower the delay or ignore robots.txt.
- Never commit `data/`.
