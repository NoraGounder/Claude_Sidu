# Quailworks: decisions for its own outbound (2026-11-10)

Quailworks is its own client here. Operating rule (CLAUDE.md rule 8): Quailworks decides from
quailworks.xyz, public data and its own results, records each decision with what would change it,
and moves on. No questionnaires. Results (replies, meetings, won deals) change decisions.

Sources: quailworks.xyz (this repository's `index.html`, read 2026-11-10); the public Polish company
register (KRS 0001108506, checked 2026-11-09, `docs/quailworks-handoff.md`); the user's answers in the
session of 2026-11-10 (1-3 clients so far, an industrial and manufacturing engineering background,
the US as the target market, a first engagement under $3,000); the lessons of The Marble Jar build.

## Offer and copy

- **Q1. Lead offer: done-for-you outbound.** Quailworks builds and runs the system that finds companies
  showing a reason to buy, writes to the right person from facts on that company's own website, and
  books the first call; the client's team takes the calls and keeps the system. Why: it is the first
  service on quailworks.xyz ("Outbound Automation: AI-powered lead research, personalised outreach at
  scale, and automated follow-up sequences"), it is the one service with a running system and a live
  client, and the email itself shows the work. Workflow automation and AI agents (services 2 and 3)
  are not pitched in email 1; they come up in replies and calls. Change if: replies ask more often
  for workflow automation or agents than for pipeline.
- **Q2. Ownership is the differentiator.** "You own the system, completely" and "We build on your
  existing stack" (quailworks.xyz) go into email 1 as "you own the system when we're done".
- **Q3. No claims we cannot back.** No results, meeting counts, response rates, timelines ("working
  systems in days" stays on the website, not in cold email), guarantees or prices in outreach.
  Quailworks has one client, The Marble Jar, launching in late November 2026, and no results yet.
  Change if: real results exist (then quote them, with the client's permission when named).
- **Q4. Proof without names.** The Marble Jar is never named in outreach (no permission, and its
  campaign has not run yet). The proof is the system itself: email 2 says this email came out of the
  same kind of system, which is true (signal found, facts crawled, draft written by the engine).
- **Q5. Next step: a 30-minute call.** Email 3 offers a lower-commitment alternative: a list of 10
  companies in the prospect's market showing one of these signals now, each with its source. It is
  made with Layers 1-2 only (company-level data, no personal data), at most 5 a month, and costs
  under $1 each. Change if: requests exceed 5 a month (raise only if they turn into calls).
- **Q6. Price:** never in email. On calls, the first engagement is under $3,000 (the user's answer,
  2026-11-10), project-based or retained as the website says. Change if: three calls in a row stall
  on price, or three sign without hesitation (then raise it).
- **Q7. Voice:** short, plain, engineer-to-engineer, in the founder's name, in English. Openings are
  questions that presume nothing (handoff copy rules); Jev 1.14's fact check falls back to a safer
  opening automatically.

## Targeting

- **Q8. Market: the United States only, for now.** Why: the largest market for outbound services,
  B2B cold email is lawful there with an opt-out and a postal address (CAN-SPAM), and it was the
  user's choice (2026-11-10). Poland, where Quailworks is registered, and Germany require prior consent
  even for business email, so they are out. The UK and Ireland come later if the US message works.
  Change if: US results are poor after 200 contacts while replies show interest from elsewhere.
- **Q9. Who: companies that sell to manufacturers and industrial operators.** Phase 1 segments:
  industrial automation and robotics (LinkedIn 147, 3247, 3248), software for manufacturing (4, with
  the search word "manufacturing"), and engineering services (3242, with the search word
  "industrial"). Why: the founder's industrial background is an edge no SaaS-focused outbound agency
  has, quailworks.xyz sells "engineering-grade thinking ... the same rigour as industrial processes",
  and these companies sell a considered product to a buyer who is hard to reach (plant and operations
  people), so they depend on trade shows, distributors and referrals. Phase 2 (off): measuring and
  control instruments, electrical equipment (983, 2468), industrial machinery (135, 55, 928).
  Change if: one segment produces most conversations (move the budget there).
- **Q10. Size: 11-200 employees** (LinkedIn bands 11-50 and 51-200), sweet spot 20-150. Why: sales is
  founder-led or a small team with no RevOps or sales-development function, which is what a
  done-for-you system replaces, and a first engagement under $3,000 is an easy decision at this size.
  Change if: meetings come mainly from one band.
- **Q11. Who we email:** sales and business-development leaders first, then marketing leaders, then
  the CEO, founder or owner at companies up to about 150 people. Never the SDRs or BDRs themselves.
- **Q12. Why now (signals):** hiring for sales roles that find new business (SDR, BDR, inside sales,
  business development, account executive) is the strongest signal: it is the work the system takes
  over (the handoff's lesson from The Marble Jar: hiring for the work you replace beats fit).
  Then: exhibiting at trade shows, a CRM or sales tool named in a job ad, rep or distributor-driven
  sales, and growth. Weights in `scoring.yaml`. Change if: `learn` shows another signal converts better.
- **Q13. No lookalikes yet.** The Marble Jar (a Dutch automation studio) is not like these targets, so it
  is excluded but not used as a lookalike. Our own won deals become the list (`best-clients`).

## Data, compliance and conflicts

- **Q14. Never The Marble Jar's data.** Quailworks finds its own prospects with its own runs. The DPA
  with The Marble Jar (article 8.4) and GDPR purpose limitation forbid reusing its accounts, contacts
  or replies, and the engine scopes every table by client. The Marble Jar is excluded
  (`icp.yaml` domains, `private/exclusions.csv`): a client is never prospected.
- **Q15. No conflict with The Marble Jar.** While it is a client, Quailworks does not prospect automation
  or software studios in the Netherlands or Belgium, and does not pitch operations or finance
  automation to its segments. The US-only, industrial-seller ICP keeps the two apart.
- **Q16. Controller, notice and footer.** For its own outreach Quailworks is the controller, so no DPA is
  needed. Every first email carries the data source, an opt-out and the postal address from the
  company register: Quailworks sp. z o.o., ul. Mikołaja Reja 34, 26-225 Gowarczów, Poland.
  Suppression is honoured and `retention` deletes data on schedule (GDPR applies because Quailworks
  is established in the EU, whoever the recipient is).
- **Q17. Sender.** The founder, President of the Management Board (public register), sends in their own
  name from Quailworks' own domains. Consent stays `pending` in `client.yaml` until the founder confirms
  in the launch "go" message, so drafts are previews until `private/sender.yaml` exists.

## Sending and budget

- **Q18. Sending domains:** two brand variants of the company name, picked in this order from what is
  available: getquailworks.com, quailworkshq.com, tryquailworks.com. Never quailworks.xyz itself, and
  never The Marble Jar's domains. Two mailboxes per domain in the founder's real name (SmartSenders,
  fresh at $4.50 a month: discovery waits for December's Apify credit anyway, so the 2-3 week warm-up
  costs no time). Own Smartlead campaigns prefixed `QW` in the existing Smartlead account.
- **Q19. Volume:** Tier 1-2 only, at most 20 emails a day at launch (4 mailboxes at 5-10 a day while
  they finish warming), Tuesday to Thursday on US Central time. Scale only what `learn` shows works.
- **Q20. Budgets** (`limits.yaml`). Apify's free $5 credit is shared with The Marble Jar, which used
  $4.80 of it in November 2026 and needs no new discovery for its launch, so Quailworks' first
  discovery runs on or after 1 December 2026 (about $3.60 for 900 companies). FullEnrich credits are
  shared too (about 770 left): Quailworks is capped at $20 a month (about 360 credits, roughly 80
  Tier 1-2 accounts), so no new credits are bought. Jev 1.14 and MillionVerifier: $2 each.
- **Q21. CRM:** Quailworks' own free HubSpot portal, only once meetings exist, through its own token
  (`client.yaml` crm.hubspot_token_env = HUBSPOT_TOKEN_QUAILWORKS), so deals never land in a client's CRM.

## Needed from the user (only what we cannot do ourselves)

One message, at launch:

1. **Buy the two sending domains and four mailboxes** (Q18), which needs a card.
2. **Confirm the founder sends in their own name**, and fill `private/sender.yaml` (name, title,
   booking link). One line.
3. **"Go"** to start sending (CLAUDE.md rule 3), after looking at the first approved drafts.

Everything else is decided above.
