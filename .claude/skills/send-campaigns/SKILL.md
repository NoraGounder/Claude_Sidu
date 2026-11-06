---
name: send-campaigns
description: Run Layer 6 of the Quailworks lead engine. Uploads approved, gate-ready leads to Smartlead (one campaign per region, mailboxes checked, one contact per company at a time), starts a campaign only with explicit approval, and syncs replies, bounces and unsubscribes back with TypeSafe Jev 1.14 reply classification. Use when asked to upload leads, launch, start or pause a campaign, or check replies.
---

# Layer 6: Smartlead

Smartlead takes its API key in the URL, so the cloud proxy cannot add it. Run these commands where
`SMARTLEAD_API_KEY` is set for real (a laptop with `.env`). The key is scrubbed from all errors.

1. `python -m gtm --client <client> push` is a dry run: eligible leads per region and why others are held.
2. `push --live` creates (or reuses) one campaign per region in `sending.yaml`, checks mailboxes (at most
   `max_per_mailbox_per_day`, warm-up on), sets sequence, schedule and settings, and uploads leads.
   **The campaign is not started.** Open it in Smartlead and check sequence, settings (tracking off,
   stop on reply, plain text), schedule and mailboxes, ideally with one test lead to a seed inbox you own.
3. `start --region <region> --i-confirm` makes Smartlead send. **Only run it after the user says so in this
   conversation.** Never run it on your own initiative.
4. `sync` (daily, or more often once replies come in): replies are classified by Jev 1.14 after masking
   emails, phones and names. `interested`, `question` and `referral` need a human answer within 2 business
   hours (Layer 7 handoff). Unsubscribes and bounces are suppressed here and blocked in Smartlead.

Guards (in code): approved draft, contact `ready` in Layer 4, consent granted in client.yaml, real
`private/sender.yaml`, not suppressed, one active contact per company (`stagger_days_same_account`).
Never weaken them, never set `ignore_*` lists to true, and never raise sending caps yourself.
