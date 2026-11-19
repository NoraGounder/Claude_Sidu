# The Marble Jar: launch plan (updated 2026-11-17)

Goal: new paying clients for The Marble Jar at the lowest cost. Measured in conversations,
proposals and won revenue, not emails sent. One won project pays for a year of tools, so the
plan optimises for **speed to real conversations with the right companies**, not for volume.
Decisions behind every line are in `decisions.md` (D1-D24); the fixes from the audit of 16 November
are in `work-order-2026-11-17.md`.

## Where it stands (17 November)

| Step | Count |
|---|---|
| Companies found (Harvest 6 Nov, BlitzAPI by admin vacancy 17 Nov) | about 1,260 |
| Tier 1 / Tier 2 (every one has a Jev-confirmed admin vacancy) | 48 / 44 (84 NL, 7 BE) |
| Tier 1-2 companies with someone to email | 78 |
| Contacts with a work email (Tier 1-2) | 121, all held until the MillionVerifier re-check (D17) |
| Approved drafts (Tier 1-2) | 118: identity and opt-out in every email |
| Mailboxes | 6 in Mithun's name: getmarblejar.com (Google) 3, marblejarhub.com (Outlook) 3 |
| Spend this month (data and AI) | about $23: Apify $4.80, FullEnrich $17.85, Jev $0.35; BlitzAPI on the Quailworks plan |

## Launch sequence

1. **Backups on** (D23): Sidarth creates the private repository `quailworks-vault` and saves
   `GTM_BACKUP_KEY` and `GTM_BACKUP_REMOTE` in the cloud environment. `push --live` and `start`
   refuse to run until the database is backed up off-site.
2. **Rehearsal** (audit C5): a test campaign to two seed inboxes Sidarth owns (one Gmail, one Outlook):
   four steps, a reply, a "stop", a bounce. Check line breaks, threading, sender name, `sync`, `handoff`.
3. **Launch day** (about 25 November, after Sidarth's "go"): warm-up check (D15: 14 days and 95%),
   `gate --recheck` (about $0.80), `gate`, `push` dry run, then `push --live` and
   `start --region nl --i-confirm`. Belgium rides in the NL campaign (D20).
4. **One message to Mithun**: booking link, the list of companies for information (D11), the DPA
   notice (Annex 2 update and BlitzAPI as sub-processor; `dpa-annex-2-update.md`).

## Running (from launch)

- **Volume:** at most 40 emails a day (`limits.yaml`), Monday to Thursday, 09:00-16:30 Amsterdam.
  About 10 new companies a day; one contact per company at a time, the second 21 days later.
  Best companies first (D16).
- **Every working day:** `sync` (replies, bounces, stops), `handoff` (briefs for replies that need a
  person; Sidarth forwards them to Mithun within 4 working hours), `backup`.
- **Pause at once** on any spam complaint, or above 3% bounces in a day (D18 conditions).
- **December:** no new companies uploaded after 12 December; follow-ups to people already in the
  sequence run until 18 December; everything pauses 19 December to 5 January.
- **Monthly:** `discover-hiring` and `discover-hiring --postings` (BlitzAPI, flat plan) for companies
  with a fresh admin vacancy, then `prefilter`, `jev`, `contacts`, `gate`, `draft`, `approve`.

## Scale or change (D19)

- **Scale** after the first booked meeting or three positive replies: a paid Apify plan or deeper
  BlitzAPI searches, Tier 3 with a vacancy, then the US, UK and Ireland.
- **Change the message, not the volume** if every first-batch contact has had emails 1 and 2 with no
  positive reply. The weekly `learn` report shows conversations per opening, tier, persona and region.

## Monthly cost (USD)

| Item | Plan | Per month |
|---|---|---|
| Smartlead | Pro, shared with Quailworks | 94 (shared) |
| Mailboxes | 6 SmartSenders mailboxes, fresh, $4.50 each | 27 |
| Domains | 2 sending domains | about 2 |
| BlitzAPI | Quailworks' Start plan, The Marble Jar capped at 5,000 records | 0 extra |
| FullEnrich | credits as used (this month about $18) | under 55 (cap) |
| Apify | free plan | 0 |
| MillionVerifier | re-checks at launch | about 1 |
| TypeSafe Jev 1.14 | per request | under 1 |
| **Total for The Marble Jar** | | **about 30-85, plus the shared Smartlead** |
