# Quailworks website

The production site for **quailworks.co**, the GTM engineering firm.

```
site/                 everything that gets published
  index.html          homepage
  privacy.html        privacy notice
  404.html            not-found page
  _headers            security headers (CSP, HSTS, …) and caching
  assets/css|js|fonts self-hosted styles, script and fonts (no third-party requests)
  og.png, favicon.svg, apple-touch-icon.png, robots.txt, sitemap.xml
wrangler.jsonc        Cloudflare deploy config (serves ./site)
docs/                 internal notes, never published
```

There's no build step. Edit the files in `site/` and deploy.

## Decisions

| Area | Choice | Why |
|---|---|---|
| Domain | **quailworks.co** | Exact brand match, credible for enterprise buyers, and short. `quailworks.com` belongs to an unrelated company, and `.xyz` reads as low-trust and hurts email deliverability. |
| Hosting, DNS, email | **Cloudflare**, one account | Domain sold at cost, free global hosting and DDoS protection, and free email forwarding for `hello@quailworks.co`. Every push to `main` deploys automatically. |
| Contact form | FormSubmit, with a mailto fallback | Works on static hosting with no server or account. Submissions arrive at `hello@quailworks.co`. |
| Analytics | Cloudflare Web Analytics | Cookie-free, so no cookie banner is needed. |
| Fonts | Self-hosted (Geist, Geist Mono, Instrument Serif) | Faster, GDPR-clean, and lets the CSP block all third-party scripts. |

## One-time setup (about 15 minutes, needs the account owner)

Payment details can't be entered by Claude, so these steps are yours. Everything after them is handled from Claude Code.

1. **Create a Cloudflare account** at dash.cloudflare.com and add a payment method.
2. **Buy the domain:** *Domain Registration → Register Domains* → `quailworks.co`. Keep auto-renew on.
3. **Connect this repo:** *Workers & Pages → Create → Import a repository* → GitHub → `NoraGounder/Claude_Sidu`.
   - Production branch: `main`
   - Build command: *(leave empty)*
   - Deploy command: `npx wrangler deploy` (auto-detected from `wrangler.jsonc`)
4. **Attach the domain:** open the new `quailworks-site` Worker → *Settings → Domains & Routes → Add → Custom domain*. Add `quailworks.co`, then `www.quailworks.co`.
   Then go to *Rules → Redirect Rules → Templates → "Redirect from WWW to root"*.
5. **Set up email:** *Email → Email Routing* on `quailworks.co` → create `hello@quailworks.co` → forward to your Gmail → verify.
6. **Activate the form:** submit the contact form once on the live site. FormSubmit emails an activation link to `hello@`; click it.
7. **Turn on analytics:** *Analytics & Logs → Web Analytics → Add site → quailworks.co*.

## Day to day

Ask Claude Code for any change. It edits `site/`, checks the result on desktop and mobile, and pushes. Cloudflare builds a preview for every branch and publishes `main` to quailworks.co within about a minute.

To preview locally:

```bash
npx wrangler dev
```

## Content still to add

- [ ] 2–3 case studies with numbers (the biggest gap compared with competitors; see `docs/gtm-agency-benchmark.md`)
- [ ] Client logos, once you have permission
- [ ] A booking link (Cal.com or Calendly) alongside the form
- [ ] Partner badges (Clay, HubSpot) once earned
