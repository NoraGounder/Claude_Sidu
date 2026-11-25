# Quailworks Engineering: decisions (2026-11-19)

Quailworks' second offer: mechanical design engineering for hardware teams, sold through the same lead
engine and tools as Quailworks' own GTM outbound. The user (2026-11-19): use Quailworks to win engineering
design contracts anywhere in the world, hire people to do the work as it grows, and "borrow the tools and
software stack from the Quailworks GTM outbound pipeline ... have one because we're already paying for a
subscription". Operating rule (CLAUDE.md rule 8): decide, record what would change it, move on.

**Objective: the most qualified engineering conversations per dollar**, measured in replies, calls and
won engagements, not emails sent.

Sources: the founder's CV (shared 2026-11-19, kept out of this repository), Quailworks' own decisions
(`clients/quailworks/decisions.md`, cited as quailworks Qn) and its launch numbers (`docs/playbook.md`).

## Inherited from Quailworks (keep unless this client's results say otherwise)

- **T1. Signals before lists.** Write only to companies with a dated reason and quote its source; Jev checks
  each job-ad match first (`ai.yaml job_evidence`).
- **T2. Verify before sending.** Every address waits for MillionVerifier (`gate.yaml verify_statuses`);
  catch-alls at most 15%.
- **T3. Best first** (`sending.yaml send_order`).
- **T4. Warm mailboxes only.** 14 days and 95% reputation; 5 a day per mailbox in week 1, 10 in week 2,
  15 after, each step only with bounces under 2% and no complaints.
- **T5. One contact per company at a time**, Tier 1-2 only at launch.
- **T6. A low-effort ask.** Email 1 offers something useful with no call (here: the engineer's profile, E6).
- **T7. Cleaned company names** (`company_suffixes`, `company_name_cut`).

## This client's decisions

- **E1. One stack, nothing new to subscribe to.** Every tool Quailworks already pays for is shared, each
  with this client's own caps in `limits.yaml` (the budget guard counts clients separately):
  BlitzAPI's flat plan (discovery by hiring signal, job postings, work emails; 5,000 of its 200,000 monthly
  records), Harvest on Apify (UK industry searches), FullEnrich (email fallback), MillionVerifier (prepaid
  checks), TypeSafe Jev 1.14 through OpenRouter, the one Smartlead account (`QWE` campaigns), Quailworks'
  own HubSpot portal (`HUBSPOT_TOKEN_QUAILWORKS`; deals read "Quailworks Engineering | company"), and the
  Notion GTM Brain. Same company and same founder, so one CRM is right. Would change: the engineering work
  growing into its own company or brand (then its own portal).
- **E2. The one thing not shared: mailboxes.** A sending domain belongs to one client (engine rule), and
  Quailworks GTM's eleven mailboxes are its own limit: about 164 new leads a week once all are warm, with
  286 contacts already waiting (quailworks Q48). Splitting them would slow the GTM launch and mix two
  offers on one reputation. Needed from the user: **one domain with three SmartSenders mailboxes** in the
  founder's name, warm-up on (about $13.50 a month plus about $13 a year), bought through the existing
  Smartlead account. Three mailboxes at 15 a day is about 45 new leads a week, enough for a market of a
  few hundred Tier 1-2 companies. Until they are warm (14 days), outreach is the warm list and LinkedIn
  (E10). Would change: GTM mailboxes left idle (then lend one domain by moving it in `sending.yaml`).
- **E3. Offer: design capacity on demand** (`offer.md`). A senior mechanical design engineer on the
  client's programme from next week, concept to released, toleranced drawings, as a day rate (how
  companies already buy contract designers) or a fixed-price package with a written scope. The client
  keeps design authority. "Any domain or industry" (the user) is the long-term reach; the first campaigns
  stay where the CV is proof (E5), because engineering buyers hire specialists. Would change: replies
  asking for another kind of work (analysis, manufacturing engineering) more than for design.
- **E4. Market: the UK first, the US second, by email; the rest of Europe by LinkedIn and referrals.** The
  UK has the densest cluster of motorsport, performance-vehicle and space companies, the founder's own
  track record, a one-hour time difference and no export-control barrier; PECR allows business email to
  limited companies with an opt-out. The US is the largest market for EV, space, eVTOL and robotics, with
  CAN-SPAM rules. Germany, Poland, Denmark and other consent-first countries: no cold email (quailworks Q8);
  their companies (including hypercar makers) are reached through the warm list and LinkedIn by hand.
  Would change: one market booking calls at under half the other's cost after 100 contacts each.
- **E5. Who: companies with 11-500 employees that design their own hardware, hiring a design engineer.**
  Segments, strongest proof first: motorsport and performance or low-volume vehicles (25 points), space,
  aerospace and eVTOL (25), robotics and machine builders (20), energy hardware (15, test). Size: big
  enough to have an engineering team, small enough to buy without a preferred-supplier list. The best
  signal is an open mechanical design role (35 points): the work exists now, budget is set aside, and hiring
  takes months (Quailworks' "hiring for the work you replace", quailworks Q12). Then CAD named in job ads,
  new programmes, funding, shows and growth. Parked: tier-1 parts suppliers (price-led, preferred-supplier
  lists), and US defence and ITAR-controlled work, which needs US persons; Jev's ICP fit marks it poor.
  Would change: `learn` showing a parked type replying well.
- **E6. Free first step: the engineer's one-page profile.** Email 1 asks "Shall I send you a one-page profile
  with the parts I've designed and the CAD I work in? No call needed." It answers the buyer's first question
  without a meeting; the call is offered with it. **Needed before the first send:** the profile itself
  (a PDF built from the CV; employer names are fine there, as on LinkedIn). Would change: profiles requested
  but not turning into calls (then offer the call first).
- **E7. Claims.** Programme types, never names, in cold email and in this repository ("hypercar and race-car
  suspension, a championship-winning touring car, launch-vehicle turbopump components", all in the CV);
  names stay in the profile and on LinkedIn (quailworks Q2: endorsement and NDA risk). "I", not "we" or
  "our engineers", until there is a bench. No rates, team size, results or timelines beyond "next week".
  `banned_phrases` stops drafts that break this. Would change: hires on the bench (then "we" and a named
  team); replies asking "who for?" (then point to LinkedIn in email 2).
- **E8. Price (calls and proposals only).** Day rate quoted per engagement, never below what the founder
  earned as a contractor; fixed-price packages at estimated days x day rate + 15%; monthly invoicing in
  arrears, packages 30/40/30. Margin on hired engineers comes later, from the gap between their cost and
  the client's day rate. Would change: three calls stalling on price, or three accepting at once.
- **E9. Website.** quailworks.co sells GTM engineering; a prospect who looks up the sender's domain should
  find the engineering offer. Proposed: a `/engineering` page (offer, CAD, part types, the founder, contact),
  linked from the footer. A public change, so it needs the user's OK; ready before the first send.
- **E10. Warm list and LinkedIn first.** The founder writes personally to 20-30 people from past programmes
  and contract agencies; the fastest first contract, and free. Former employers go in `private/exclusions.csv`
  so the engine never cold-emails them. The day after email 1, a plain LinkedIn connection request to Tier 1
  contacts (`linkedin` command), by hand, about 5 a day. The headline must mention design engineering.
- **E11. Engineering consultancies are partners, not prospects.** They sell the same thing, so the engine
  never emails them (`not_a_buyer`, `name_keywords`, 0 fit points). Overflow subcontracting with them is
  worth having, but by personal introduction, not a sequence. Would change: a partner programme the founder
  wants to run at volume (then a separate client with its own copy).
- **E12. One founder, one conversation per company.** Quailworks GTM sells to sales leaders at robotics,
  industrial-software and aerospace companies; this offer sells to engineering leaders, sometimes at the
  same companies. `sending.yaml avoid_overlap_with: [quailworks]` holds any company Quailworks GTM emailed
  in the last 90 days (engine change of 2026-11-19, `l6_send.overlap_companies`, company names and domains
  only). Since 2026-11-24 `push` also reads Quailworks GTM's `QW` campaigns in the shared Smartlead account,
  because each chat has its own database (the GTM chat's question). Quailworks GTM can add the mirror rule
  (`avoid_overlap_with: [quailworks-engineering]`) in its own `sending.yaml` once this engine code is on its branch. Would change: never, while one person sends both.
- **E13. Delivery as it grows.** The user plans to hire engineers and outsource the work. Before the first
  hire: a contractor agreement with NDA, IP assignment and flow-down of each client's terms; professional
  indemnity insurance for Quailworks sp. z o.o.; client consent where a contract restricts subcontracting;
  no export-controlled data to anyone the client has not approved. The founder checks every drawing until
  the bench is proven. Recorded here so the offer never promises what delivery cannot keep.

- **E2 update (2026-11-24): no new domain; two of Quailworks' own are lent (the user: "yes, go ahead").**
  The user does not want to buy more domains. Quailworks now has 16 mailboxes on 6 domains (quailworks Q50), all
  in the founder's name, active and at 97-100% warm-up reputation except one at 89% (Smartlead, read 2026-11-24).
  Quailworks GTM's ramp is a campaign total of 30 a day in week 1, 60 in week 2 and 90 after, so it needs about six
  mailboxes at 15 a day. Proposed: move **quailworks.work** (3 Google, warm from 30 November) and **quailworks.dev**
  (3 Outlook, warm from 4 December) to this client. Quailworks GTM keeps getquailworks.com, quailworksforward.com,
  teamquailworks.com and quailworkshq.com: 10 mailboxes, 150 a day of headroom for a 90-a-day ramp. Each domain
  still belongs to one client, so replies, bounces and reputation stay separate per offer. Sharing all 16 between
  both offers was rejected: the engine's per-mailbox ramp would be counted twice and one offer's bounces would hurt
  the other. Final split, confirmed by the user in the GTM chat the same day (quailworks Q51, commit 6adb4aa):
  Quailworks GTM keeps getquailworks.com, quailworksforward.com and teamquailworks.com (8 mailboxes, 120 a day
  of capacity for its 90-a-day ramp), this client has quailworks.work and quailworks.dev, and quailworkshq.com
  sends the founder's acquisition outreach (clients/eta). Done: `mailbox_domains` moved to this folder,
  sender consent recorded, and the Quailworks chat told before its next push (its uploads link newly warm
  mailboxes by themselves, the first of these on 30 November). Would change: GTM replies needing more volume than 10 mailboxes.
- **E9 update (2026-11-24): the page is built.** `site/engineering.html` (quailworks.co/engineering): the offer,
  the two ways to buy, the one-page profile, the engineer, an FAQ (CAD, remote work, IP, export control, cost) and
  an enquiry form tagged "Engineering: ..." in the email to hello@. Linked from the homepage founder section and
  footer and listed in the sitemap. It ships with the site's new dark "studio" theme. Not live until the user says
  "deploy".

- **E14. Everything that BlitzAPI can do runs on BlitzAPI (2026-11-24, the user: "use as much as we can").**
  Company discovery moves from Harvest on Apify to BlitzAPI's company search (`discover-companies`, hiring.yaml
  `company_searches`, the same six markets), and people search from FullEnrich to BlitzAPI's title waterfall
  (`scoring.yaml enrichment_policy.people_first: blitzapi`, the personas as tiers in priority order). FullEnrich
  stays only for companies BlitzAPI returns nobody for, and for emails BlitzAPI does not find, each within its
  $20 cap; Apify's cap for this client is 0. The records cap rises from 5,000 to 10,000 of the plan's 200,000.
  Checked on the live API the same day: company search found 476 UK companies under 500 people with "motorsport"
  as a keyword; people search returns the current job title, location and LinkedIn profile. Every company still
  goes through Layer 2 (crawl, signals, Jev) and every address through MillionVerifier. Would change: BlitzAPI's
  people search missing the right person at more than a third of Tier 1 companies (then FullEnrich first again).

## Offer v2: the Grand Slam Offer (2026-11-25, the user: "implement Alex Hormozi's skills and create a compelling grand slam offer")

Built with the $100M Offers method; four MIT-licensed Hormozi skills (github.com/alexsmedile/hormozi-skills) are
vendored in `.claude/skills/` for every chat. Full offer: `offer.md`. The user can veto any number before the
first send.

- **E15. From a day rate to a dated outcome: the First-Part Sprint.** v1 sold capacity on a day rate, which
  buyers compare hour for hour with agency contractors (a commodity). v2 sells one part, scoped in writing,
  supplier-ready in two weeks at a fixed price (from £4,500 / $6,000; £8,500 / $11,500 for a sub-assembly),
  then continuity as an Embedded Design Engineer at £600 / $850 a day, month to month, with the Sprint fee
  credited if they continue within 30 days. Value Equation: the dream outcome is the build date met; time
  delay and effort are where we win (fixed start, two weeks, the Standards Pack, one review a week). Would
  change: three calls in a row stalling on the Sprint price, or Sprints running past 7.5 days of our time.
- **E16. Lead magnet: the 40-Point Release Check** (`assets/40-point-release-check.md`), offered in email 1 instead of
  the one-page profile (E6). It is useful on its own, needs no call and no data from the prospect, and reveals
  the release backlog the Sprint solves. After a reply, the free Drawing Check (one released drawing marked up
  within 48 hours under NDA) gives proof on their own work. Would change: checklists requested but no replies
  after it (then lead with the Drawing Check).
- **E17. Supplier-Ready Guarantee (conditional).** "If your part isn't supplier-ready by the date in the scope,
  you don't pay for the Sprint", plus supplier-found errors of ours fixed in two working days, unbilled.
  Conditions: inputs on day one, review feedback within two working days, the date moves for delays on the
  client's side. One claim costs about 7.5 days of our time; Hormozi's guarantee math says a promise that lifts
  first purchases pays for several claims. Cold emails state it in plain words without the word "guarantee"
  (banned phrase). Would change: two claims in the first ten Sprints.
- **E18. Scarcity and urgency, both real.** Two Sprints start a month, on the 1st and the 15th, which is today's
  real capacity; a slot closes five working days before its start. Motorsport gets a seasonal name (the
  Pre-Season Part Sprint, October-February). Would change: capacity growing with vetted engineers (E13).
- **E19. Company voice.** The user (2026-11-24): Quailworks is its own thing. Emails and the site speak as
  Quailworks ("we"); the sender introduces himself as being "with Quailworks Engineering". Never headcount
  ("our engineers", "team of" are banned), never results we have not had, programme types only. This replaces
  the "I" rule in E7.

- **E20. Live (2026-11-25, the user: "make the checklist PDF and deploy").** The 40-Point Release Check is a branded
  three-page A4 PDF (`assets/40-point-release-check.pdf`, built from the .md with Chromium print: tick boxes,
  drawing fields, the noes tally and the Drawing Check offer), attached to the "interested" reply. quailworks.co
  is deployed with the company-first content, the WebGL heroes, the motion layer and the engineering page selling
  the First-Part Sprint (Worker version 727e1e1e). Checked live: WebGL renderer active, no founder content, the
  four engineering form options, no console errors, no horizontal scroll at 390px.

- **E21. Offer v2's numbers stand, and the pipeline runs (2026-11-25, the user: "the kind of desired results that I
  want, make the right judgment and go ahead").** Quailworks keeps E15-E18 as written: Sprint from £4,500 / $6,000,
  embedded £600 / $850 a day, the Supplier-Ready Guarantee, two Sprints a month. The pipeline runs to approved
  drafts the same day. Not taken as approval to send: the first real emails in the founder's name wait for his
  explicit "go" on drafts he has seen (CLAUDE.md rule 3), and the mailboxes only become warm on 30 November and
  4 December anyway. Off-site backups were not available in this session (the vault repository could not be
  attached), so the database is backed up, encrypted, on this machine only until it is.

- **E22. First run and calibration (2026-11-25).** BlitzAPI found 1,677 companies (company searches 1,567, hiring
  searches 222, 830 live design postings matched to 215 of them); 1,327 passed the first filters; Layer 2 and Jev
  left 66 in Tier 1-2; 110 decision-makers were selected (BlitzAPI people search, FullEnrich only for missing
  emails); 103 work emails; MillionVerifier checked every one; 69 passed the gate; 67 drafts were approved
  automatically, 67 of them opening with the company's own open design role. Spend: $2.04 (FullEnrich $1.46,
  MillionVerifier $0.41, Jev $0.17), BlitzAPI 2,904 records on the flat plan. Calibration, read as the founder
  would: US spacecraft, launch and military-drone companies were landing in Tier 1 although their work is
  export-controlled (ITAR) and needs US persons. Fixed by (1) a scoring rule (`itar_required`, -60) for ITAR,
  US-person, export-control and clearance wording on their pages, (2) a sharper `buyer_profile` that Jev judged
  every company against again (`jev --redo`, $0.07): spacecraft companies fell to Tier 3, civil eVTOL stayed, and
  (3) one US military-drone maker added to `private/exclusions.csv` by hand. Two drafts for a UK/German hypersonics
  company are left for the founder (likely defence work). Upload plan: 40 first contacts (28 US, 12 UK); 27 second
  contacts wait 21 days. Would change: replies showing a segment or country converting better (E4, quailworks Q27).

## Needed from the user (only what we cannot do ourselves)

See `client.yaml needed_from_client`. In one message: the domain and three mailboxes (E2), the one-page
profile (E6), OK on the website page (E9), the warm list (E10), and the "go" (CLAUDE.md rule 3).
