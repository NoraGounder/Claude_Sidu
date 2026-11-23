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

## E8. The US is the primary market; Form 5500 is the US base (2026-11-23)

**Decision.** Sidarth's next business is to be found in the US first (his call, 2026-11-23); the UK and Poland run
in the background. The US search now starts from the Department of Labor's Form 5500 filings (free, public, every
employer with a retirement plan, filed each year): 2024 active participants are the headcount, the earliest plan
effective year is a floor on company age, 2021 vs 2024 participants is growth, and a final filing (plan ended)
drops the company. The PPP file (E6) is joined on name + ZIP for a firm-specific payroll; PPP borrowers with no
plan stay in as a second, weaker tier. Revenue = headcount x industry revenue per employee, blended with the PPP
payroll estimate when there is one and kept within 0.6x-1.6x of the industry norm (`us.revenue_clamp`). The person
who signed the filing for the employer is stored as a contact (data/ only), usually the owner or president.

**Why.** PPP alone was 2020-21 and estimated size from a loan. Form 5500 is current (2024), counts people directly,
shows growth, and a plan started in 2000 or earlier is the best free sign of a long-tenured, older owner.

**First run.** 48,041 employers with a plan in the 25 NAICS codes and 33,785 PPP borrowers (6,373 in both): 75,475
candidates; sieve 1 pass 2,585, review 10,280. Among passes: median 71 employees, median revenue estimate about
$16M, most with a plan since 2000 or earlier and headcount up from 2021.

**What would change it.** Owner-age data (a paid people-data source) would replace plan age as the seller signal;
the 2025 filings (complete in late 2026) replace 2024 as the base.

## E9. Industry bar lowered to 20; US owner lookup built, not yet funded (2026-11-23)

**Decision (Sidarth, 2026-11-23).** `industry_scorecard.min_score` goes from 22 to 20. Every industry Jev 1.14
scored so far landed between 18.9 and 21.5, so 22 qualified nothing; 20 is still inside the Primer's example range
(20-28).

**Owner lookup.** `eta-owners` takes each US sieve-2 survivor with a verified website and asks FullEnrich's people
search (paid, 0.25 credit, about $0.014, per person returned) for its owner, president or CEO. Age is estimated from
the first degree's start year (about 18) or end year (about 22), else from the first listed job (about 22, a floor);
tenure is the start of the current role. Both are "unverified" in the ledger. The ETA FullEnrich cap is $0 until
Sidarth sets one: the dry run shows the cost.

**What would change it.** Low hit rates on small firms (owners often have thin LinkedIn histories) would move the
lookup to BlitzAPI's profile enrichment, or to the Form 5500 signer plus a people-data match on name.
