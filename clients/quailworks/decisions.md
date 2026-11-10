# Quailworks: decisions for its own outbound (2026-11-10)

Quailworks is its own client here. Operating rule (CLAUDE.md rule 8): Quailworks decides from its
website, public data and its own results, records each decision with what would change it, and moves
on. No questionnaires. Results (replies, meetings, won deals) change decisions.

Sources: **quailworks.co** (the live site, read 2026-11-10; the user confirmed it is the current site,
not quailworks.xyz, which is this repository's older `index.html`); the founder's CV (shared by the
user 2026-11-10, kept out of this public repository); the Polish company register (KRS 0001108506,
`docs/quailworks-handoff.md`); the user's answers of 2026-11-10 (1-3 clients so far, the US as the
market, a first engagement under $3,000); the lessons of The Marble Jar build.

## Offer and copy

- **Q1. Lead offer: signal-based outbound, built as a system.** quailworks.co sells three systems
  (signal-based outbound, inbound routing, RevOps and CRM data) and says to "start with the system that
  hurts most". Outbound leads because it is the system this engine runs, it has a live client, and the
  email itself shows the work. Inbound routing, CRM data and AI research agents come up in replies and
  calls, not in email 1. Change if: replies ask more for inbound or CRM work than for pipeline.
- **Q2. Differentiators, in this order:** (1) the founder spent over a decade as a mechanical design
  engineer on aerospace and high-performance automotive programs, choosing and managing suppliers: the
  person engineering sellers are trying to reach (CV); (2) "we were an engineering firm before we were a
  GTM firm": specs before automations, production standards (quailworks.co); (3) "you own everything",
  built inside the client's own tools (quailworks.co). Employer and program names stay out of cold
  email and out of this repository.
- **Q3. No claims we cannot back.** No results, meeting counts, response rates, guarantees, prices, or
  build times (the site's "typical build 2-4 weeks" stays on the site). Quailworks has one client, The
  Marble Jar, launching late November 2026, and no results yet. Change if: real results exist (then
  quote them, with the client's permission when named).
- **Q4. Proof without names.** No client names. The proof is the system itself: email 2 says this email
  came out of the same kind of system, which is true.
- **Q5. Next step: the site's own offer.** A 30-minute working session, and a written note on the three
  things we would fix first, whether or not we work together (quailworks.co contact section). Email 3
  offers a lighter alternative: 10 companies in their market showing a signal now, each with its source
  (Layers 1-2 only, company-level data, at most 5 a month, under $1 each).
- **Q6. Price:** never in email. On calls, the path on quailworks.co: a GTM audit at a fixed fee (the
  first engagement, under $3,000, the user's answer), then a build sprint quoted after the audit, then an
  embedded team or a handover. Change if: three calls in a row stall on price, or three sign without
  hesitation (then raise it).
- **Q7. Voice:** short, plain, engineer-to-engineer, in the founder's name, in English (UK spelling on
  the site; US spelling in emails to US buyers). Openings are questions that presume nothing; Jev 1.14's
  fact check falls back to a safer opening automatically.

## Targeting

- **Q8. Market: the United States first, then the UK and Ireland.** The US is the largest market and was
  the user's choice; B2B cold email is lawful there with an opt-out and a postal address (CAN-SPAM). The
  UK is next: the founder studied and worked there, and PECR allows business email with an opt-out.
  Poland and Germany require prior consent even for business email, so they are out.
  Change if: US results are poor after 200 contacts.
- **Q9. Who: companies that sell to hardware engineering teams in aerospace, space, automotive and
  advanced manufacturing.** Phase 1: aerospace and space suppliers (LinkedIn 52, 1), automotive parts
  suppliers (1042), and software for manufacturing and engineering teams (4, search word
  "manufacturing"). Why: their buyers are design, test and supplier-quality engineers, whom generic
  sales emails do not reach, and the founder was that buyer for over a decade (CV); quailworks.co's
  "engineering firm before a GTM firm" positioning fits them. Also searched from the start, because
  discovery is cheap: automation and robotics (147, 3247, 3248) and engineering services (3242, search
  word "aerospace"). Phase 2 (off): precision parts (876, 840), instruments and electrical equipment
  (983, 2468), industrial machinery (135, 55, 928).
  Change if: one segment produces most conversations (move the budget there).
- **Q10. Size: 11-500 employees** (LinkedIn bands 11-50, 51-200, 201-500), sweet spot 30-300. Why:
  quailworks.co sells to revenue teams with a CRM to build in, but a fixed-fee audit under $3,000 is an
  easy decision up to about 500 people; above that, procurement slows a new firm down.
  Change if: meetings come mainly from one band.
- **Q11. Who we email:** sales and business-development leaders first (in aerospace, the director of
  business development is often the senior seller), then marketing leaders, then the CEO, founder or
  owner at companies up to about 150 people. Never the SDRs or BDRs themselves.
- **Q12. Why now (signals):** hiring for sales roles that find new business (SDR, BDR, inside sales,
  business development, account executive, sales engineer) is the strongest signal: it is the work the
  system takes over (The Marble Jar lesson: hiring for the work you replace beats fit). Then: exhibiting
  at trade shows (aerospace, automotive and manufacturing shows), a CRM or sales tool named in a job ad,
  rep or distributor-driven sales, and growth. Weights in `scoring.yaml`.
  Change if: `learn` shows another signal converts better.
- **Q13. No lookalikes yet.** The Marble Jar (a Dutch automation studio) is not like these targets, so it
  is excluded but not used as a lookalike. Our own won deals become the list (`best-clients`).

## Data, compliance and conflicts

- **Q14. Never The Marble Jar's data.** Quailworks finds its own prospects with its own runs. The DPA
  with The Marble Jar (article 8.4) and GDPR purpose limitation forbid reusing its accounts, contacts or
  replies, and the engine scopes every table by client. The Marble Jar is excluded (`icp.yaml` domains,
  `private/exclusions.csv`): a client is never prospected.
- **Q15. No conflict with The Marble Jar.** While it is a client, Quailworks does not prospect automation
  or software studios in the Netherlands or Belgium, and does not pitch operations or finance automation
  to its segments. The US-first, engineering-seller ICP keeps the two apart.
- **Q16. Controller, notice and footer.** For its own outreach Quailworks is the controller, so no DPA is
  needed. Every first email carries the data source, an opt-out and the postal address from the company
  register (quailworks.co shows none): Quailworks sp. z o.o., ul. Mikołaja Reja 34, 26-225 Gowarczów,
  Poland. Suppression is honoured and `retention` deletes data on schedule (GDPR applies because
  Quailworks is established in the EU, whoever the recipient is).
- **Q17. Sender.** The founder, President of the Management Board (public register), sends in their own
  name from Quailworks' sending domains. Consent stays `pending` in `client.yaml` until the founder
  confirms in the launch "go" message, so drafts are previews until `private/sender.yaml` exists.

## Sending and budget

- **Q18. Sending domains:** two brand variants of the company name, picked in this order from what is
  available: getquailworks.com, quailworkshq.com, tryquailworks.com. Never quailworks.co itself (it
  carries the company's own Google Workspace mail and DMARC), never quailworks.xyz, and never The Marble
  Jar's domains. Two mailboxes per domain in the founder's real name: fresh SmartSenders mailboxes
  (about $4.50 a month each) on these brand domains, warmed up for 2-3 weeks. Pre-warmed mailboxes only
  come on unrelated domain names, which do not carry the Quailworks brand (the user, 2026-11-10), so
  they are not used. The warm-up runs in parallel with discovery, scoring, contacts and drafts, so the
  first sends wait only on the mailboxes. Own Smartlead campaigns prefixed `QW` in the existing
  Smartlead account.
- **Q19. Volume:** Tier 1-2 only. After warm-up, 5 a day per mailbox (20 a day), rising to 10 each
  (40 a day) after a clean first week (bounces under 2%, no spam complaints); warm-up stays on.
  Tuesday to Thursday on US Central time. Scale only what `learn` shows works.
- **Q20. Budgets** (`limits.yaml`, raised on the user's say-so of 2026-11-10). Apify's free $5 credit is
  shared with The Marble Jar and was used up in November, so the user moves the account to a paid plan
  (Starter) and Quailworks may spend $15 a month on discovery (the first run, 1,500 companies, is about
  $6). FullEnrich credits are shared and the user tops them up: Quailworks may spend $40 a month (about
  730 credits, roughly 150 Tier 1-2 accounts). Jev 1.14 $3, MillionVerifier $2. The Marble Jar's caps
  are unchanged.
- **Q21. CRM:** Quailworks' own free HubSpot portal, only once meetings exist, through its own token
  (`client.yaml` crm.hubspot_token_env = HUBSPOT_TOKEN_QUAILWORKS), so deals never land in a client's CRM.

## Needed from the user (only what we cannot do ourselves)

Purchases now, in parallel with the first runs (they need a card):

1. **Two brand sending domains and four fresh SmartSenders mailboxes** in the founder's name, with
   warm-up switched on the same day (Q18).
2. **A paid Apify plan** (Starter) and **a FullEnrich top-up** (Q20).

At launch, one message:

3. **Confirm the founder sends in their own name**, and fill `private/sender.yaml` (name, title,
   booking link). One line.
4. **"Go"** to start sending (CLAUDE.md rule 3), after looking at the first approved drafts.

Everything else is decided above.
