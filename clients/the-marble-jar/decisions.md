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
  a Recruitee feed could, later); BlitzAPI for discovery and emails (coverage of Dutch SMEs untested).
  Revisit after the first 100 contacts.

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

## Needed from Mithun (only what we cannot do for him)

One message, at launch, a few minutes:

1. **Done (11 November 2026):** Mithun accepted the data processing agreement in writing
   (GDPR Art. 28). The user keeps his message as the signed copy.
2. **A booking link or two time slots a week** for meetings. Until then, Quailworks forwards
   interested replies to him and proposes times.

Everything else is decided above.
