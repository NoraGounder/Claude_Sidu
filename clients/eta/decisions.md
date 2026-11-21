# ETA search: decisions

Same rule as every client (CLAUDE.md rule 8): decide, record what would change the decision, move on.
The design lives on the whiteboard "ETA Deal Sourcing Pipeline"; this file records what was built from it.

## E1. UK first, Poland next (2026-11-19)

The buy box is any industry, any country, highest return. Sieve 1 only works on real numbers where small
private companies must publish accounts. Of those markets, the UK is the one with a free, documented API that
covers all three things sieve 1 needs:

- **Discovery:** Companies House advanced search filters every active UK company by industry code (SIC),
  incorporation date, status and location.
- **Owners:** persons with significant control and directors come with month and year of birth, so owner age
  (the succession signal) is public.
- **Accounts:** every electronically filed set of accounts is iXBRL, so balance sheets, employees and, where
  filed, the profit and loss account can be read without a person.

Limits: small UK companies may leave out the profit and loss account, so sieve 1 sometimes falls back to a
profit proxy (growth in retained earnings) and marks turnover and margin as *unknown* in the evidence ledger;
the owner conversation fills the gap. Poland (KRS + RDF) publishes full statements for every sp. z o.o. but
has no free search by industry, so it comes second.

Would change it: a free Polish source that searches companies by PKD code, or a decision to buy in Poland.

## E2. Industry list as a starting search, not a preference (2026-11-19)

The search needs SIC codes. eta.yaml starts with essential, recurring, unglamorous B2B services and light
industry (repair and maintenance, testing and calibration, waste and drainage, building services, cleaning,
pest control, security systems, machining). That matches the board's value rules and Permanent Equity's
"boring business" thesis, and it can be widened at any time: the screen ranks on financials, not sector.

## E3. What milestone 1 builds (2026-11-19)

Registry discovery, company profile, filed accounts (iXBRL), owners (PSC and directors), the sieve-1 screen
with a 0-100 score, the evidence ledger, and a ranked CSV. No outreach, no AI calls, no paid vendors:
Companies House is free (600 requests per 5 minutes per key). Sieve 2 (Jev 1.14: simple, moat, AI exposure,
industry score), owner outreach, the deal pack and the investor engine come next and reuse Layers 4-7.

## E4. Personal data (2026-11-19)

Owner and director names and birth month/year come from the public register and stay in data/ (gitignored),
with the source recorded on every row. Nothing about a specific company or person is committed or sent to
Notion. Before any outreach, the UK GDPR legitimate-interest assessment is written like The Marble Jar's.

## E5. Selection criteria: Stanford Search Fund criteria and Hamilton Helmer's 7 Powers (2026-11-20)

Sidarth's instruction: qualify each business with the Stanford Search Fund investment criteria (2026 Primer,
Part IV) and Hamilton Helmer's 7 Powers. This replaces the earlier guessed bars.

- **Sieve 1, Stanford company criteria, public numbers.** Hard fails only where the register proves an
  "undesirable" trait: turnaround (insolvency history, operating loss, negative equity), too small (under $10M
  revenue or $1.5M EBITDA), group-owned (no motivated owner-seller). Scored: revenue $10-30M and EBITDA in range,
  EBITDA margin above 15% (under 10% is thin), return on tangible capital above 20%, history of cash generation,
  motivated seller (owner 60+), management bench (a director under 55). Dollars converted at £0.79 per $.
  EBITDA = operating profit + depreciation; without the depreciation note, operating profit (a floor).
  ROTC is approximated by return on capital employed (equity plus net debt).
- **Sieve 2a, Stanford industry scorecard** (Primer p.30): ten criteria scored 1-3 by Jev 1.14, once per SIC
  code; 22 of 30 is the bar (the Primer's examples score 20-28).
- **Sieve 2b, 7 Powers:** Jev 1.14 rates each Power from the company's own website, found by domain guess and
  accepted only when the site shows the registered company number. A Power needs a Benefit and a Barrier.
  At least one Power with clear evidence is required to be "qualified"; each is an `unverified` claim in the
  evidence ledger to test with the owner. Websites are weak evidence, so a missing site means "watch", not out.

Tension recorded: Stanford's size floor ($1.5M EBITDA) sits above where the board's value rules expected the
steepest discounts (under ~$1M profit). Following Stanford, sub-floor companies now fail when their accounts show
it. Would change it: Sidarth choosing a smaller first deal, or the floor leaving too few qualified companies.

## E6. United States: SBA PPP file for discovery and size (2026-11-21)

**Decision.** The US search starts from the SBA's public Paycheck Protection Program file (loans of $150k+, 2020-21,
free, data.sba.gov). It lists every borrower with NAICS code, jobs, loan amount, business type and age. A first-draw
loan was 2.5 months of payroll, so payroll ~ 4.8 x loan and revenue ~ payroll / the industry's payroll share
(`eta.yaml` `us.payroll_share`). Sieve 1 for the US scores these proxies (`us.sieve1`); sieve 2 is the same Stanford
industry scorecard (per NAICS code) and 7 Powers as the UK. A US website counts only if it shows a name word plus
the ZIP code or the city and state.

**Why.** The US has no public register of private-company accounts. The PPP file is the largest free list of US
private companies with a size measure, and it covers every industry.

**Limits.** Data is from 2020-21: a company may since have closed or been sold (sieve 2's website check catches most).
Pay is capped at $100k a head in the loan formula, so high-pay firms look smaller. Revenue is an estimate (+/- 30%)
and every derived number is "unverified" in the ledger. No owner names or ages: they come from the broker or owner.
Race, ethnicity, gender and veteran fields are never read into the database.

**First run (2026-11-21).** 33,785 borrowers in the 25 target NAICS codes after the prefilter; 6,574 pass and
7,735 review; the best 3,000 are stored. Sieve 2 trial on the top 10: 4 verified websites, 0 clear Powers, industry
scores 18.9-20.3 of 30 (all "watch").

**What would change it.** A paid US private-company data source with real revenue (if Sidarth wants one), or
state registry data for owner details (some states are in the Alexandria catalogue: CO, GA, MO, NH, TX).

## E7. Poland: KRS open API; numbers only through rejestr.io if Sidarth buys it (2026-11-21)

**Decision.** Polish discovery uses the KRS open API (api-krs.ms.gov.pl, Ministry of Justice, free, no key). It
cannot search by industry, so `eta-pl` reads the daily KRS bulletin (every company with a register entry that day,
including filing annual accounts), reads each new number's current extract once, and keeps sp. z o.o. and S.A.
companies whose main PKD code is in `eta.yaml` `pl.pkd_codes`. Sieve 1 scores registration age, accounts filed on
time, owner age (when the extract shows a full PESEL; only birth year and month are kept), owner-operated and share
capital, and fails liquidation, bankruptcy, late filing and group ownership. Without filed numbers a Polish company
can reach "review", never "pass".

**Why.** The KRS is the official register, public and free. The filed statements are in the RDF repository, which is
behind bot protection (Incapsula): it is not crawled (house rule: no getting around protections). rejestr.io resells
the same statements as JSON: 500 zł per 10,000 requests, 0.5 zł per statement in JSON. That is a spend Sidarth
decides; until then numbers come from the owner.

**Status.** Code and tests are built against the API's documented JSON. On 2026-11-21 the API showed its maintenance
page (Przerwa techniczna) all day, so there is no live run yet: `eta-pl` stops cleanly and resumes next time.

**What would change it.** Sidarth approving rejestr.io (then a `rejestr_io` source fills Revenue, EBITDA, employees
and net assets, and Polish companies can pass), or the bulletin turning out not to list accounts filings (then
discovery moves to rejestr.io's PKD search).
