---
name: send-gate
description: Run Layer 4 of the Quailworks lead engine, the send gate. Deterministic checks on every contact with an email (suppression, role and free-mail addresses, domain match, contact country, email status, catch-all cap, freshness, sender consent, GDPR data source) before anything is sent. Use when asked which contacts are ready to email, or to check list quality.
---

# Layer 4: send gate

Free and deterministic: `python -m gtm --client <client> gate`. It re-checks every contact with an
email each time, so rule changes in `clients/<client>/gate.yaml` apply to all of them.

- `ready`: every rule passes. Only these go to Layer 5 and 6.
- `held`: may pass later. Usual reasons: `sender_consent_pending` (client.yaml
  sender.consent_to_send_in_name is not "granted"), `stale_email` (re-check needed),
  `catch_all_cap_reached`, `catch_all_not_allowed_for_tier_3`.
- `rejected_l4`: never send (suppressed, role or free-mail address, unrelated domain, contact
  outside NL/BE, invalid email, no data source).

Stale emails (older than `freshness_days`): `gate --recheck` re-checks only those with
MillionVerifier. Its API takes the key in the URL, so run this where MILLIONVERIFIER_API_KEY is set
for real (a laptop with .env); the cloud proxy cannot add it.

Never mark a contact ready by hand, never set consent to "granted" without the client's written
consent, and never print lists of contacts in chat.
