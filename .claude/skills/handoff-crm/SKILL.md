---
name: handoff-crm
description: Run Layer 7 of the Quailworks lead engine. Turns replies that need a person into deals and one-page meeting briefs (with the first answer to send), records meeting outcomes and won revenue, mirrors deals to HubSpot free, and reports which signals and openings produce meetings and money. Use when asked about replies to answer, meetings, briefs, deal outcomes, the CRM, pipeline or what is working.
---

# Layer 7: handoff, CRM and learning

Run after every `sync` (Layer 6). Speed matters: an interested reply should get an answer within
4 working hours.

1. `python -m gtm --client <client> handoff` (free, sends nothing). Interested, question and referral
   replies become deals at stage `interested` with a brief in `data/briefs/` (local only: it holds names
   and the reply). "Not now" becomes stage `later`. Other replies are closed.
2. Quailworks sends the brief's "First answer" from the Smartlead inbox in the sender's name, then the
   calendar invite and the brief to the client. Never promise integrations, timelines, prices or free
   work (`decisions.md`).
3. `outcome <contact_id> <stage> [--value EUR] [--note ...]` records what happened: `booked`, `held`,
   the client's one word (`qualified`, `not a fit`, `follow up`), `no show`, `proposal`, `won`, `lost`.
   A won company is suppressed from outreach and added to best clients as a lookalike.
4. `deals`: deals by stage, meetings held, open pipeline and won revenue. `learn`: the same per signal,
   opening, process, tier, persona and region. Move effort to what wins money, not to what gets opens.
5. `crm` is a dry run of the HubSpot mirror. `crm --live` writes companies, contacts and deals
   (HubSpot free, `HUBSPOT_TOKEN` private app token; never deletes). **CRM writes need the user's
   approval in this conversation** (CLAUDE.md rule 3).

Do not print contact names, emails or brief contents in chat; point to the brief file instead.
