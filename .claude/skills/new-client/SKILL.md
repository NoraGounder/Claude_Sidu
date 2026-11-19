---
name: new-client
description: Set up the Quailworks lead engine for a new client (or a new outbound for Quailworks itself) from clients/_template, in the order that worked for Quailworks' own launch. Use when asked to onboard, add, start or copy the pipeline for a new client, or to reuse the Quailworks setup elsewhere.
---

# New client: from website to launch-ready

The engine has no client logic of its own; a client is a folder of config. Start from `clients/_template/`
(Quailworks' setup with the client-specific values blanked, every protection switched on). Costs and
lessons with numbers: `docs/playbook.md`. Rules: `CLAUDE.md` (public repo, budget guard, no sending,
CRM writes or deletes without the user's approval, decide instead of asking the client).

## 1. Create the folder (free)

```bash
cp -r clients/_template clients/<slug>
```

Then, in this order, from the client's website and public data only (no questionnaire):

| File | Rewrite | Keep |
|---|---|---|
| `client.yaml` | identity, language, sender mode, `crm.hubspot_token_env` | `consent_to_send_in_name: pending` |
| `offer.md` | the offer, the promise and the free first step, what a qualified meeting is | the structure |
| `icp.yaml` | segments (Layer 1 searches), personas (Layer 3), hard exclusions | size band logic, exclusions of agencies, recruiters |
| `scoring.yaml` | `detect` signal rules, weights, `job_boards.countries` | `job_boards`, `quote_width`, `matches_per_label`, `enrichment_policy` |
| `ai.yaml` | `not_a_buyer`, `job_titles`, `contact_question` wording | `job_evidence`, thresholds, Jev-only policy |
| `brain.yaml` | pains, objections, competitors, voice (mark each confirmed/decided/hypothesis) | the status labels |
| `templates/sequence.yaml` | hooks, steps, `cta`, `market_line`, `title_role_words`, `banned_phrases` | `named_facts`, short steps, `{gdpr_notice}` last |
| `templates/replies.yaml` | answers and `call_prep` | the categories |
| `hiring.yaml`, `markets.yaml`, `sample.yaml` | roles, industries, countries, `never_name` | refresh cadence |
| `gate.yaml` | `contact_countries`, `gdpr_notice` (legal name, postal address, sources) | `verify_statuses`, catch-all cap |
| `sending.yaml` | `campaign_prefix`, `mailbox_domains`, `regions`, schedule | `send_order`, `min_warmup_*`, `spread_daily_cap` |
| `limits.yaml` | nothing until the user approves a budget | trial caps |
| `decisions.md` | Q1... one entry per decision, with what would change it | the inherited T1-T7 |

Write `private/sender.yaml` and `private/exclusions.csv` (current customers, partners, competitors) last.
`private/` is gitignored; check `git status` before every commit.

## 2. Check before spending (free)

```bash
cd engine && pytest -q
python -m gtm --client <slug> discover --dry-run
python -m gtm --client <slug> discover-hiring --dry-run
```

A sending domain may belong to one client only: `push` stops if two `sending.yaml` files list it.

## 3. First run, small (paid, each step after its dry run)

1. Layer 1: 50-100 companies per segment (`discover` or `discover-hiring`).
2. Layer 2: `prefilter`, then `jev`. Read `tiers --tier tier_1 --verbose`: if a third of Tier 1 looks
   wrong, fix `scoring.yaml`/`ai.yaml` and `prefilter --rescore` before going on.
3. Layer 3: `contacts --dry-run`, then `contacts --limit 10`, then the rest of Tier 1-2.
4. Layer 4: `gate --recheck` (MillionVerifier; the key goes in the URL, so it must be an environment variable).
5. `markets --refresh` (if `market_line` is used), `draft`, `approve`; read five drafts in full.
6. `funnel`: cost per step for this client only. Quailworks' first run: about $0.22 per verified contact.

## 4. Launch (needs the user)

Mailboxes warm for 14 days. `push` (dry run) shows which mailboxes are ready and why others are held.
`push --live` uploads with campaigns paused; `start --region <r> --i-confirm` only after the user's "go".
Then daily `sync` + `handoff`, weekly `funnel`, `learn`, `markets --refresh`, and the ramp in decisions T4.

## Mistakes we already made (do not repeat)

- Market lists named recruiters, integrators and the prospect's own vendors: fill `never_name` and
  `exclude_title_words` before the first `markets --refresh`.
- Company names with legal suffixes, (R) signs and bracketed abbreviations: check `company_suffixes`.
- A mailbox with warm-up just switched on counted as ready: keep `min_warmup_days`.
- The per-mailbox cap rejected every mailbox whose Smartlead ceiling was higher: keep `spread_daily_cap`.
- A free-trial vendor blocked after 74 checks: buy the small prepaid pack before a verification run.
- Tests assert config values: after changing a client's config, run `pytest -q` and commit only on green.
