# Work order: The Marble Jar, launch fixes (2026-11-17)

From the read-only audit of 16 November 2026 (commit 8a9b2bb, 97 tests passing) and Sidarth's
decisions of 17 November (`decisions.md` D18-D24). This file is the implementing session's task list.

**Status 2026-11-17 (evening):** done in this session, see the ticks and decisions D25-D28. Open: the
vault repository and key (Sidarth), the C5 rehearsal (needs seed inboxes and Sidarth's OK), H6
placement test, M1 captcha redirect, M11 second-contact email, M12 DMARC address, BlitzAPI emails
(after Mithun's notice), the scheduled runs after launch, and the launch itself.
Work top to bottom; tick items off here as they land, in the same commit.

## Rules for the implementing session

- Read `CLAUDE.md` first. Its hard rules win over anything below.
- Edit only `clients/the-marble-jar/` plus the shared engine code an item names. Every shared change
  gets a test and a dated "Between chats" note on the Notion page "Quailworks GTM Brain"; message the
  Quailworks chat directly when it must know before its next run.
- No sending, no uploads, no Smartlead or HubSpot writes, no cap raised without Sidarth's approval in
  the chat. Dry run before any new kind of paid run.
- Never print contact names or emails in chat, commits or Notion. Counts only.
- Record each changed decision in `decisions.md`. Before every push: `git pull --rebase`, run
  `pytest -q`, check `git status` for data files.

## Decisions already made (do not reopen)

| Audit item | Decision |
|---|---|
| C1 Dutch consent law | D18: send the first, already enriched Dutch batch by email; Sidarth accepts the risk. Conditions: low volume, identity and opt-out in every email (H1), every stop honoured at once, pause on any complaint. |
| H2 website pointer | D22: email 2 keeps pointing to the invoice example on themarblejar.io; the site is being refreshed. |
| H8 volume and budget | D19: proof first. No new paid discovery until 1 booked meeting or 3 positive replies. Use what is already paid for: FullEnrich credits, BlitzAPI's flat plan (D24). Speed first (C2). |
| C4 backups | D23: encrypted snapshots in a separate private GitHub repository, latest 14, auto-restore, weekly copy to Sidarth. |
| M2 Dutch copy | D21: English only (Mithun does not speak Dutch). |
| M7 Belgium | D20: Belgian Tier 1-2 companies go in the NL campaign, same risk and conditions as D18. |
| (new) BlitzAPI | D24: use the Quailworks BlitzAPI plan for discovery by admin vacancy and for work emails. |

## Numbers at audit time (16 November)

- 1,193 companies found on 6 November; 838 passed Layer 1. Tier 1: 40, Tier 2: 66, Tier 3: 718.
- Tier 1-2: 100 Dutch, 6 Belgian. Sendable: 105 people at 70 companies (22 Tier 1, 48 Tier 2).
- 133 approved drafts, all held until `gate --recheck` (D17). Spend $17.43. Nothing uploaded or sent.
- Smartlead: 6 mailboxes (getmarblejar.com 100% warm-up reputation; marblejarhub.com 86-96%).
- BlitzAPI probe (17 November, 93 records of the plan's 200,000): 68 companies in NL/BE, 50-500
  employees, in our sectors, with an admin vacancy posted in the last 30 days. 47 are new to us;
  of the 21 we have, 11 are Tier 1-2 and 10 sit in Tier 3 (our crawl missed their vacancy).

## Tasks, in order

### 1. C4: backup and restore (D23) - protects everything after it
- [x] `python -m gtm --client <c> backup`: SQLite online backup of `data/engine.db` plus
      `clients/<c>/private/`, gzip, encrypted with `GTM_BACKUP_KEY` (symmetric, e.g. `age` passphrase
      mode or `cryptography` Fernet). Never logs the key.
- [ ] Destination: a separate private GitHub repository (proposed name `quailworks-vault`, created
      only after Sidarth approves). One folder per client; keep the latest 14 snapshots, older ones
      deleted. Never this code repository.
- [x] `restore`: newest snapshot back into `data/`; run automatically when a session finds no
      database. Test the round trip on synthetic data.
- [x] Backup after every state-changing command; `push --live` and `start` refuse when the last
      backup is older than the last change.
- [ ] Weekly: send Sidarth the encrypted file (SendUserFile).
- Sidarth's one-time steps: approve the vault repository; save `GTM_BACKUP_KEY` in the cloud
  environment's settings and in his password manager.
- Shared engine code: Between-chats note; the Quailworks chat can use the same command.

### 2. C2: upload throttle (shared code)
- [x] `engine/gtm/layers/l6_send.py`, `push`: `per_region = max(1, daily // 4 // len(regions))`
      divides by all three defined regions, giving 3 new leads a day (first wave about 8 weeks).
      Divide by the regions that have leads to send. Target: about 10 new leads a day, 40 emails a
      day in steady state (launch plan).
- [x] Test with three regions defined and leads in one. Between-chats note.

### 3. D20 Belgium
- [x] `sending.yaml`: region `nl` countries `[NL, BE]` (same time zone).
- [x] `gate.yaml`: `contact_countries` add `BE`.
- [x] Then `draft` and `approve` for the Belgian contacts (6 Tier 1-2 companies, about 9 contacts).

### 4. D24 BlitzAPI: discovery by admin vacancy and work emails
- [x] `clients/the-marble-jar/hiring.yaml` (model: `clients/quailworks/hiring.yaml`): Dutch and English
      admin job titles (administratief medewerker, medewerker administratie, financieel administratief
      medewerker, medewerker orderverwerking, order entry, medewerker binnendienst, data entry,
      crediteuren-/debiteurenadministratie, administrative assistant, accounts payable),
      `posted_last_days: 30`, `job_countries: [NL, BE]`, searches per `icp.yaml` segment with
      LinkedIn industry names (Wholesale, Wholesale Import and Export, Wholesale Building Materials,
      Construction, Civil Engineering, Specialty Trade Contractors, Machinery Manufacturing,
      Industrial Machinery Manufacturing, Electrical Equipment Manufacturing, Food and Beverage
      Manufacturing, Transportation/Logistics/Supply Chain and Storage, Truck Transportation,
      Warehousing and Storage, Facilities Services).
- [x] `limits.yaml`: `blitzapi: 0` and `"blitzapi:record": 0.0` (flat plan), `blitzapi_records: 5000`
      a month (Quailworks keeps 20,000; the plan allows 200,000). This is a new cap Sidarth approved
      in principle on 17 November; confirm the number with him.
- [x] `discover-hiring --dry-run`, then live. Then `prefilter` (Layer 2 still confirms the vacancy on
      the company's own site) and `jev`. Existing Tier 3 accounts that BlitzAPI shows hiring should
      be re-scored (`prefilter --rescore` for those).
- [ ] `scoring.yaml` `enrichment_policy.email_first: blitzapi` (FullEnrich for the misses). Before the
      first person-level call: the notice to Mithun under DPA 5.2 that BlitzAPI is a new
      sub-processor goes into the launch message (task 10).
- [x] Shared resource (the Quailworks plan): Between-chats note and a direct message to the
      Quailworks chat with the cap.

### 5. C3, H4, H5: qualification
- [x] C3: `open_roles` counts any careers-page link as a role (navigation, duplicates, divisions).
      It drives the "open roles" opening in 24 drafts and `headcount_growth`'s 10 points in 77 of
      106 companies; 34 keep their tier only through those points. Count only titles Jev judged real
      vacancies, de-duplicate, stop quoting the number unless confirmed ("several open roles").
      `l2_prefilter.py` (`signal_score`), `l5_copy.py` (`facts_for`).
- [x] H4: `manual_process_language` is a plain word match ("Excel" is in most job ads). Put it
      through the Jev evidence check like job ads, or require an admin vacancy for Tier 2.
- [x] H5: 13 Tier 1-2 companies are local arms of international groups; the -15 penalty moves none
      below Tier 2. Add a Jev question ("part of a larger international group?") that caps them at
      Tier 3.
- [x] Then `jev --redo` for the changed questions, `prefilter --rescore`, check the tiers.

### 6. H3: contacts for Tier 1 companies without one
- [x] 18 of 40 Tier 1 companies have nobody to email (12 no matching title). Add to the personas in
      `icp.yaml`: Controller, Financial Controller, Hoofd Administratie, Manager Finance & Control,
      Directeur, Eigenaar, DGA, Bedrijfsleider, Hoofd Bedrijfsbureau, Manager Customer Service,
      Teamleider Administratie.
- [x] `contacts --dry-run`, then live for those companies (BlitzAPI first once task 4 is done;
      FullEnrich credits already bought), then `gate`.

### 7. H1 and copy fixes (D18 conditions)
- [x] H1: every step gets a signature (Mithun Martin Mendez, title, The Marble Jar, Breda) and steps
      2-4 a short opt-out line. `l5_copy.auto_approve` must require the opt-out in every step.
- [x] M3: tidy quoted job titles (no city names, proper case; drop titles that are not admin work).
- [x] M4: names with "|" separators, "Ing." in greetings, "Services's" possessives.
- [x] M5: an opening for a Jev-confirmed admin vacancy whose title is not quotable.
- [x] M8: remove "40,000 to 50,000 euros a year" and "usually a one-off investment" from email 3.
- [ ] M11: the second contact at a company gets a different first email.
- [x] `draft --redo`, `approve`, spot-check 10 drafts.

### 8. Docs, dead settings, DPA
- [x] M9: update `launch-plan.md`, the `scoring.yaml` comments, the `icp.yaml` buyer profile (NL and
      BE first), the `.gitignore` header (repository now private), and the send-campaigns skill.
- [x] M10: `new_ops_or_finance_leader` (15 points) has no code: build it or remove it.
- [x] H9: amend DPA Annex 2 (cloud container, encrypted backups in the private GitHub vault,
      BlitzAPI as sub-processor), write the one-page legitimate interest assessment, confirm two-factor
      login on every tool and the vendors' data terms. Notice to Mithun goes in task 10.

### 9. C5 rehearsal, H6 deliverability, H7 operations
- [ ] C5: a test campaign with two seed leads (Gmail and Outlook inboxes Sidarth owns), all four
      steps, a reply, a "stop" and a bounce. Check line breaks in plain text, threading, sender name,
      then `sync` and `handoff`. `push` must read and store Smartlead's upload response, and a failed
      campaign setup must not leave an unknown campaign behind. Needs Sidarth's approval to create it.
- [ ] H6 and M14: inbox placement test for both domains; watch marblejarhub.com daily (D15 keeps
      mailboxes under 95% out).
- [ ] H7 (pause rule and complaint category done, D28): scheduled `sync` and `handoff` three times each working day; Smartlead reply notification
      to Sidarth; automatic pause above about 3% bounces or on any spam complaint; uploads into an
      active campaign need Sidarth's approval.
- [x] M6: consider Monday-Thursday sending; pause from about 19 December to 5 January.
- [ ] M1: the sending domains show a captcha page before redirecting; ask SmartSenders for a plain
      redirect.
- [ ] M12: DMARC report address away from the sending mailboxes. M15: close the stuck run row.

### 10. H10: the one message to Mithun
- [x] (sent 25 Nov; booking link still awaited) Booking link (or two fixed slots a week); the company list for information (D11); the DPA
      notice (Annex 2 changes, BlitzAPI). Sidarth sends it.

### 11. Launch
- [ ] `backup`, `gate --recheck` (D17), `gate`, `push` dry run, show Sidarth the counts, then wait
      for his "go" before `push --live` and `start --region nl --i-confirm`.

## What was already in good shape (keep it)

Jev 1.14 only with every call logged; budget guard and caps respected; no secrets or prospect data
in git; Tier 1 is real (each has a Jev-confirmed admin vacancy); contact titles right; copy makes no
promise The Marble Jar has not made; DNS (SPF, DKIM, DMARC p=reject) correct on both domains;
mailboxes in Mithun's name; each client tied to its own sending domains; warm-up gate, best-first
order and the email re-check are on; DPA accepted; retention coded.
