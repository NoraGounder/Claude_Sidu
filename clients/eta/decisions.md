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
