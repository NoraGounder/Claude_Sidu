# The Marble Jar: decisions Quailworks made (2026-11-09)

Operating rule: Quailworks decides, Mithun takes meetings. We do not send him questions we can
answer ourselves from his website, public data or our own results. Each decision says what would
make us change it. Results (replies, meetings, won deals) change decisions, not questionnaires.

Sources: themarblejar.io (read 2026-11-09), the user's instructions of 2026-11-06 to 2026-11-09.

## Offer and copy

- **D1. Lead offer:** design-first automation of manual operations and finance work (orders,
  invoices, data entry), plus custom software where off-the-shelf does not fit. Why: it is what the
  website leads with ("design-first. automation-driven."), and its homepage demo is an invoice flow.
  Change if: replies show a different service is wanted.
- **D2. No claims we cannot back:** no integrations, timelines ("2 to 3 weeks") or fixed prices in
  outreach. The website does not state them. Change if: Mithun volunteers them.
- **D3. Not sold in outbound:** Mendix (no longer offered), pebls and the new November platform
  (not confirmed as the same thing). Change if: the new platform is public on the website.
- **D4. Next step offered:** a 30-minute call. No free prototype or other free work is promised
  on The Marble Jar's behalf. Change if: calls do not convert and Mithun offers a free first step.
- **D5. Proof:** no client names in emails. The website shows client logos; prospects can look.
  The email can point to the invoice example on themarblejar.io (from email 2 on).
- **D6. Voice and competitors:** Quailworks writes in a short, plain, humble tone. Competitors and
  objections are learned from replies and meeting notes (`brain.yaml`).

## Targeting

- **D7. Market and order:** the Netherlands first, Tier 1-2 only, about 40 emails a day
  (`launch-plan.md`). US, UK and Ireland after the Dutch results show a working message.
- **D8. Size and industries:** 50-500 employees in logistics, wholesale, installation and
  manufacturing, as built. Change if: meetings come mainly from one size band or sector.
- **D9. Who we email:** operations and finance leaders; the owner at companies under about 150.
- **D10. Lookalikes:** the logos on the website (universities, start-ups, a multinational) are not
  like our targets, so they are excluded from outreach but not used as lookalikes. Our own won
  deals become the lookalike list (`best-clients`), so the engine learns without asking.

## Compliance and sending

- **D11. Do not contact:** every company shown on themarblejar.io is excluded
  (`private/exclusions.csv`). Before launch Mithun gets the list of companies, for information
  only: no reply needed, but he can name any to skip.
- **D12. Footer address:** The Marble Jar BV, Verlengde Poolseweg 16, 4818 CL Breda, The
  Netherlands, as published on the website.
- **D13. Sending domains:** Quailworks picks 2-3 brand variants of the company name (never
  themarblejar.io itself) and sets them up, with mailboxes in Mithun's name only (no made-up
  personas, no unrelated pre-warmed domains). Quailworks sp. z o.o. is the registrant and pays;
  if the engagement ends, Quailworks transfers the domains to The Marble Jar on request.
- **D14. Consent:** sending in Mithun's name is confirmed (2026-11-06).

## Deliverability (2026-11-16)

- **D15. Warm mailboxes only:** a mailbox joins a campaign after 14 days of warm-up and at least 95%
  warm-up reputation. Why: the Outlook mailboxes on marblejarhub.com were at 86-96% on 2026-11-16.
  Change if: Smartlead's warm-up stays below 95% for a mailbox that sends fine.
- **D16. Best first:** uploads go in order of tier, then signal and fit, so the small early volume
  reaches the strongest companies. Change if: the `learn` report shows Tier 2 replying better.
- **D17. Re-check every email before sending:** finder results rated DELIVERABLE or HIGH_PROBABILITY
  are verified again with MillionVerifier (`gate --recheck`, about $0.004 each) at launch. Why: a
  bounce rate above about 2% hurts new domains, and in a Quailworks sample 2 of 7 "deliverable"
  results failed a second check. Change if: re-checks keep agreeing with the finder.
- **Not adopted from the Quailworks build (2026-11-16):** naming hiring companies in the prospect's
  market (conflicts with D5, no names in emails); a free sample list as the ask (conflicts with D4, no
  free work promised); job-board feeds (Greenhouse, Lever and Ashby rarely cover Dutch companies;
  a Recruitee feed could, later). Revisit after the first 100 contacts. (BlitzAPI was adopted
  on 2026-11-17: D24.)

## Legal basis in the Netherlands (2026-11-17)

- **D18. First batch to Dutch companies by email, risk accepted by Sidarth.** The audit of
  2026-11-16 found that article 11.7 of the Telecommunicatiewet requires prior consent for
  commercial email to companies too (ACM), so an opt-out line alone does not make cold email to
  Dutch addresses compliant. Sidarth decided on 2026-11-17 to send the initial, already enriched
  batch of Dutch contacts anyway and accepts that risk knowingly. Conditions that keep the risk low:
  low volume (limits.yaml), the sender's full identity and an opt-out line in every email (audit
  H1), every "stop" and every unsubscribe honoured at once and suppressed for good, and a pause on
  any spam complaint. Scope: this first batch only; new Dutch contacts after it need a new
  decision. Change if: a complaint, a regulator letter, or legal advice says otherwise.

## Launch scope (2026-11-17, Sidarth's answers to the audit of 2026-11-16)

- **D19. Proof first, then scale.** No new discovery spend until the first batch has run. The
  first batch is everything already paid for: Tier 1-2 contacts with approved drafts, the Tier 1
  companies still without a contact (found with FullEnrich credits already bought, audit H3), the
  Belgian companies (D20), and BlitzAPI's flat plan for discovery by admin vacancy (D24). Because the
  fixed costs (Smartlead, mailboxes) run every month whatever we send, speed beats extra volume:
  the throttle fix (audit C2) comes first. Scale (a paid Apify plan, a monthly discovery run) as
  soon as there is one booked meeting or three positive replies. If every first-batch contact has
  had emails 1 and 2 with no positive reply, change the message, not the volume.
- **D20. Belgium is in.** The Belgian Tier 1-2 companies already in the pipeline are sent to,
  in English, in the Netherlands campaign (same time zone). Belgian law also asks for prior
  consent for email to a named person's work address, so this carries the same risk as D18 and
  the same conditions apply; Sidarth accepts it for these companies. New Belgian contacts after
  this batch need a new decision.
- **D21. English only.** Every email is in English: Mithun does not speak Dutch, so a Dutch
  reply could not be handled by him on a call. Dutch job-ad titles may still be quoted as they
  appear in the ad. Change if: replies show English costs us meetings and Mithun brings in a
  Dutch speaker.
- **D22. Website pointer stays.** Email 2 still points to the invoice example on themarblejar.io.
  The website is being refreshed to show the current services (a separate project, rule 7).
  Change if: replies mention Mendix or pebls.
- **D23. Backups (audit C4).** An encrypted snapshot of the database and `private/` after every
  state-changing run, kept off the container in a separate private GitHub repository (never this
  code repository), only the latest 14 snapshots, with a tested `restore` that runs when a fresh
  session finds no database. The encryption key lives in the cloud environment's settings and in
  Sidarth's password manager; without it the archive is unreadable, and destroying it erases every
  old copy at once. A weekly encrypted copy also goes to Sidarth's own device. `push --live` and
  `start` refuse to run when the last backup is older than the last change. Change if: Sidarth
  prefers an EU storage provider, or the DPA annex (audit H9) needs one.

- **D24. BlitzAPI for The Marble Jar.** Quailworks pays a flat BlitzAPI plan (200,000 records a
  month) and uses a small part of it, so The Marble Jar uses it too, at no extra cost: (1) discovery
  by the signal itself, companies in our sectors with an admin vacancy posted in the last 30 days,
  and (2) work emails first through BlitzAPI, FullEnrich for the misses. Test on 2026-11-17: 68
  companies in the Netherlands and Belgium (50-500 employees, our sectors) with such a vacancy; 47
  were new to us and 10 of the ones we had were parked in Tier 3 because our crawl missed the
  vacancy. Layer 2 still confirms every vacancy on the company's own site. The Marble Jar's own
  monthly records cap goes in `limits.yaml`; the Quailworks chat is told. Before BlitzAPI sees any
  person's data, Mithun gets the sub-processor notice (DPA 5.2) in the launch message. This is
  Quailworks' tool and Quailworks' cost, not a reuse of either client's data. Change if: the
  Quailworks chat needs the records, or the found emails bounce more than FullEnrich's.

## Implementation of the audit (2026-11-17, Sidarth: "whatever achieves the outcome, go ahead")

- **D25. Only companies with a confirmed admin vacancy are Tier 1-2.** The careers-page title count
  no longer counts as growth, manual-process words alone cannot make Tier 2 (10 points, was 20),
  Tier 1 needs 45 signal points (two admin vacancies), and local arms of international groups
  (Nederland, Benelux, Europe in the name, or "part of ... Group" on the site) are parked in Tier 3.
  Job postings from BlitzAPI count as vacancies once Jev 1.14 confirms the title. Result: 48 Tier 1 and
  44 Tier 2, every one with an admin vacancy; 78 have a contact. Change if: `learn` shows a parked
  group converting.
- **D26. Every email carries Mithun's full name, title and an opt-out**; `approve` refuses a draft
  without "'stop'" in every step. Email 3 no longer states a salary figure. A confirmed vacancy whose
  title cannot be quoted cleanly opens with "is hiring for admin work".
- **D27. Sending Monday to Thursday** (was Tuesday to Thursday, which stretched the sequence to about
  four weeks), no new companies after 12 December, pause 19 December to 5 January.
- **D28. Automatic pause.** `sync` pauses an active campaign on any complaint, or when more than 3% of
  uploaded leads bounced (from 20 on). Restarting needs Sidarth's OK.
- **Left open (needs Sidarth or a later run):** the backup vault repository and key; the rehearsal
  with seed inboxes; Smartlead's reply notification to Sidarth; a DMARC report address away from the
  sending mailboxes (audit M12); a different first email for the second contact at a company (M11);
  BlitzAPI as first email source once Mithun has had the sub-processor notice (D24).

## Needed from Mithun (only what we cannot do for him)

One message, at launch, a few minutes:

1. **Done (11 November 2026):** Mithun accepted the data processing agreement in writing
   (GDPR Art. 28). The user keeps his message as the signed copy.
2. **A booking link or two time slots a week** for meetings. Until then, Quailworks forwards
   interested replies to him and proposes times.

Everything else is decided above.
