# Quailworks website

The marketing site for Quailworks, a GTM engineering agency. It's a single static page (`index.html`) with no build step and no dependencies apart from Google Fonts.

- `index.html`: the whole site (HTML, CSS and JS inline)
- `docs/gtm-agency-benchmark.md`: competitor research behind the positioning

## Hosting: Cloudflare (recommended)

Cloudflare gives you the domain, DNS, hosting and a forwarding email address in one free account. You only pay for the domain, at cost. Once it's connected to this repo, **every push to `main` goes live**, and every other branch gets its own preview URL. That's what lets Claude Code manage the site end to end.

### One-time setup (about 15 minutes, done by a human)

1. **Create a Cloudflare account** at dash.cloudflare.com.
2. **Buy the domain:** Domain Registration → Register Domains. Payment details can't be entered by Claude, so this step is yours.
3. **Connect this repo:** Workers & Pages → Create → Pages → Connect to Git → pick `NoraGounder/Claude_Sidu`.
   - Production branch: `main`
   - Framework preset: `None`
   - Build command: *(leave empty)*
   - Build output directory: `/`
4. **Add the custom domain:** open the Pages project → Custom domains → add `yourdomain` and `www.yourdomain`. DNS is configured automatically because the domain is on Cloudflare.
5. **Set up email:** Email → Email Routing → forward `hello@yourdomain` to your Gmail.

### Day-to-day changes (Claude Code)

Ask Claude Code for a change. It edits `index.html` and pushes to a branch, Cloudflare posts a preview URL, and merging to `main` publishes it.

## Alternative: GitHub Pages

The repo is public, so GitHub Pages also works for free. Go to Settings → Pages → Source: *Deploy from a branch* → `main` / `root`. Then point the domain's DNS at GitHub: four `A` records to `185.199.108.153`, `185.199.109.153`, `185.199.110.153` and `185.199.111.153`, plus a `CNAME` for `www` to `noragounder.github.io`. You'd still buy the domain somewhere else, and email forwarding isn't included.

## Before going live

- [ ] Choose the domain, then update the contact email in `index.html` (search for `hello@quailworks.co`).
- [ ] Swap the mailto CTA for a booking link (Cal.com or Calendly) if you have one.
- [ ] Add case studies and client logos (see "Gaps to close" in the benchmark doc).
