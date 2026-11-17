# Data processing agreement: update to Annex 2 and the sub-processors (notice, 2026-11-17)

Notice from Quailworks sp. z o.o. (processor) to The Marble Jar BV (controller) under article 5.2 of
the data processing agreement accepted on 11 November 2026. It corrects Annex 2 to how the data is
actually handled and names one new sub-processor. No reply is needed; The Marble Jar can object
within 14 days, in which case BlitzAPI is not used for its data. Audit of 16 November, item H9.

## Annex 2: technical and organisational measures (replaces the earlier text)

1. **Where the working data lives.** The prospect database (company data, business contact
   details of the people we email, drafts, replies) is a SQLite file in an isolated cloud workspace
   run by Anthropic (Claude Code on the web) under Quailworks' account, not on a Quailworks laptop.
   The workspace is reachable only through Quailworks' login. Data is never written to the code
   repository (checked before every change).
2. **Backups.** After every change an encrypted copy (AES with a key derived by scrypt from a
   passphrase only Quailworks holds) goes to a private GitHub repository used for nothing else. Only
   the latest 14 copies exist; destroying the key makes every copy unreadable.
3. **Keys.** API keys sit in the workspace's secret store or as environment variables of
   Quailworks' private environment, never in files, emails or chat.
4. **Access.** Only Quailworks (Sidarth Thrumurthy) has access. Two-factor login is on for every tool
   account that supports it (to be confirmed per tool before launch: Smartlead, SmartSenders, FullEnrich,
   BlitzAPI, Apify, OpenRouter, MillionVerifier, GitHub, Anthropic).
5. **Minimisation.** Business contact details only: name, job title, company, work email, LinkedIn
   page and where each came from. No private emails, phone numbers or special categories. The AI
   model sees job titles and company facts; replies are masked (names, emails, phone numbers removed)
   before classification.
6. **Retention.** As agreed: contacts who did not reply are deleted after the agreed period, opt-outs
   are kept only as a suppression entry, and everything is deleted or returned when the agreement ends
   (`retention` command).
7. **Rights of the people we email.** Every email names the sender and the source of the data and
   carries an opt-out; a "stop" is honoured at once and for good.

## Sub-processors

| Sub-processor | What it does with The Marble Jar's data | Location |
|---|---|---|
| Anthropic (Claude Code) | the workspace where the engine and database run | US (EU SCCs) |
| Apify (Harvest API) | finds companies on LinkedIn (company data only) | EU/US |
| **BlitzAPI (new)** | finds companies by open vacancy; may find work emails for chosen contacts | US |
| FullEnrich | finds decision-makers and their work emails | EU (France) |
| MillionVerifier | checks that an email address exists before sending | EU |
| OpenRouter / TypeSafe Jev 1.14 | scores companies and job titles; classifies masked replies | US |
| Smartlead, SmartSenders | sends the emails from The Marble Jar's mailboxes; collects replies | US |
| GitHub (Microsoft) | stores the encrypted backups | US (EU SCCs) |
| HubSpot (only once meetings exist) | CRM mirror of deals | EU/US |
