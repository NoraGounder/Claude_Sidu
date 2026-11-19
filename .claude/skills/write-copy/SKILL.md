---
name: write-copy
description: Run Layer 5 of the Quailworks lead engine. Builds personalised email drafts from human-written templates and crawled facts only (no AI-written text); TypeSafe Jev 1.14 picks the opening angle and example process and fact-checks the opening; drafts go to Google Sheets for Quailworks review and come back approved or rejected. Use when asked to write, draft, review or approve outreach emails.
---

# Layer 5: drafts and review

1. `python -m gtm --client <client> draft` drafts every contact that is `ready` (or only waiting on sender
   consent). Without `clients/<client>/private/sender.yaml` the drafts are previews.
2. `python -m gtm --client <client> export-drafts` writes `data/<client>-drafts-review.csv`. Import it into
   Google Sheets, fill `decision` (approve / reject), edit text if needed, download as CSV, then
   `python -m gtm --client <client> import-review --file <csv>`. Delete the sheet afterwards: it holds personal data.
3. Approve nothing flagged by the fact check (`jev_fact_check`) without reading the facts column.

Rules
- Copy lives in `clients/<client>/templates/sequence.yaml`. Never invent facts: hooks only use facts with a
  source URL. Change the copy there, not in code.
- Openings ask, they don't assert things we have not verified. The fact check exists to catch that.
- Email 1 keeps the compliance notice; the import refuses approvals that remove it.
- Jev 1.14 only, no names sent to it (`ai.yaml`); never another model.
