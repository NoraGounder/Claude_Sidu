# Quailworks website and business stack

The production site for **quailworks.co**, the GTM engineering firm, plus the runbook for the domain, email and tools around it.

```
site/              everything that gets published (HTML, CSS, JS, fonts, images)
src/worker.js      edge script: serves the site, www → apex redirect, security headers
scripts/build.mjs  packs site/ into the Worker (runs automatically on deploy)
wrangler.jsonc     Cloudflare deploy config (custom domains)
docs/              internal notes, never published
```

Edit the files in `site/`, then run `npx wrangler deploy`, which packs and publishes them. The site's files ship inside the Worker rather than as separately uploaded static assets, because this cloud environment's credential proxy can't pass Cloudflare's asset-upload tokens.

## The stack (chosen for price-to-performance)

| Need | Choice | Cost | Why this one |
|---|---|---|---|
| Domain | `quailworks.co` on Cloudflare Registrar | at cost, roughly $26–30/yr | No markup on renewals, WHOIS privacy included, and Claude can manage it by API |
| Hosting, CDN, DNS, SSL | Cloudflare Workers | $0 | Global edge, DDoS protection, free tier covers 100k requests/day |
| Email, calendar, docs, video | Google Workspace Business Starter, 1 seat | $7/mo annual, $8.40 flexible | Best deliverability, and every GTM tool (Clay, HubSpot, Instantly, Apollo) plugs into Google. Aliases are free |
| Booking link | Google Calendar appointment schedule | included | No extra tool to pay for |
| Contact form | Own endpoint (`POST /api/contact` in the Worker) via Cloudflare Email Service, with a mailto fallback | $0 | No third party; validation and spam protection built in. Submissions go to `hello@` with the visitor as reply-to |
| Analytics | Cloudflare Web Analytics | $0 | Cookie-free, so no cookie banner |
| **Total** | | **about $10/month** | |

Alternatives I rejected:
- **Zoho Mail ($1/mo):** cheaper, but GTM tools integrate poorly.
- **Microsoft 365 ($6/mo):** fine, but the GTM ecosystem is Google-first.
- **Free forwarding plus personal Gmail:** fails DMARC alignment, so mail to enterprise inboxes lands in spam.

## Setup checklist

**You (anything that needs payment or an account in your name):**
1. [x] Create a Cloudflare account and add a card: https://dash.cloudflare.com/sign-up
2. [x] Buy `quailworks.co`: *Domain Registration → Register Domains*. Turn auto-renew on.
3. [x] Create the API token and save it in Claude's secure credential form (Workers, Workers Routes, Zone Settings, DNS Edit).
4. [x] Start Google Workspace (14-day free trial): https://workspace.google.com/business/signup/welcome. Use "I have a domain" → `quailworks.co`, and make your own address (e.g. `firstname@quailworks.co`). Send Claude the verification TXT value Google shows you; it isn't secret.
5. [x] In Google Admin, generate the DKIM key (*Apps → Google Workspace → Gmail → Authenticate email*), send Claude the TXT value, then click *Start authentication*.

**Claude (via the Cloudflare API):**
- [x] Deploy the site to `quailworks.co` and `www.quailworks.co` (www redirects to the apex)
- [x] SSL in Full (strict) mode, always HTTPS, minimum TLS 1.2, TLS 1.3
- [x] Google Workspace MX (`smtp.google.com`) and SPF
- [x] Google verification TXT and DKIM (added by Google's Cloudflare connection; SPF, DKIM and DMARC all PASS on a test email)
- [x] DMARC tightened to `p=quarantine` after the passing test
- [x] `hello@quailworks.co` added as an alias of `sid@quailworks.co`
- [ ] Contact form email: onboard `quailworks.co` to **Email Sending** only (never Email Routing, which would replace Google's MX), and verify `hello@quailworks.co` as a destination address
- [ ] Turn on Web Analytics, then do a final check of HTTPS, headers, email authentication and the form

## Day to day

Ask Claude Code for a change. It edits `site/`, checks the result on desktop and mobile, and runs:

```bash
CLOUDFLARE_API_TOKEN=proxy-injected CLOUDFLARE_ACCOUNT_ID=7b86034b2cd7f3d1d016aaa166a1c376 npx wrangler deploy
```

The real token is stored on the `Claude_Sidu` cloud environment and injected by its network proxy, so `proxy-injected` is only a placeholder. Any future session in this environment can deploy.

## Content still to add

- [ ] 2–3 case studies with numbers (the biggest gap compared with competitors; see `docs/gtm-agency-benchmark.md`)
- [ ] Client logos, once you have permission
- [ ] A booking link next to the form, once the Google Calendar booking page exists
- [ ] Partner badges (Clay, HubSpot) once earned
