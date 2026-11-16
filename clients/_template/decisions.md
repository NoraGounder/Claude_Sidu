# <Client>: decisions (<date>)

Operating rule (CLAUDE.md rule 8): Quailworks decides from the client's website, public data and its own
results, records each decision with what would change it, and moves on. No questionnaires.

**Objective: the most booked qualified meetings per dollar.** Every decision is judged on that.

## Inherited from Quailworks (keep unless this client's results say otherwise)

- **T1. Signals before lists.** Write only to companies with a dated reason (a job ad, a show, growth),
  and quote that reason's source. Jev checks each job-ad match before it may be quoted (`ai.yaml job_evidence`).
- **T2. Verify before sending.** Fresh mailboxes cannot afford bounces: "high probability" and even
  "deliverable" finder results wait for MillionVerifier (`gate.yaml verify_statuses`); catch-alls at most 15%.
- **T3. Best first.** Small early volume goes to the strongest companies (`sending.yaml send_order`).
- **T4. Warm mailboxes only.** 14 days and 95% warm-up reputation (`min_warmup_*`); the ramp is kept by the
  campaign's daily total (`spread_daily_cap`): 5 a day per mailbox in week 1, 10 in week 2, 15 after,
  each step only with bounces under 2% and no spam complaints.
- **T5. One contact per company at a time**, Tier 1-2 only at launch.
- **T6. A low-effort ask.** Email 1 offers something useful with no call (a sample list of companies
  showing a buying signal); the call is offered when it is delivered.
- **T7. Market names, never vendors or recruiters** (`markets.yaml never_name`), and cleaned company names.

## This client's decisions

- **Q1. Market and ICP:** ... Would change: ...

## Needed from the client (only what we cannot do ourselves)

See `client.yaml needed_from_client`.
