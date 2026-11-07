// Edge entry point for quailworks.co.
// Redirects www to the apex domain, serves the site packed from ./site
// (see scripts/build.mjs), handles the contact form at POST /api/contact,
// and attaches security headers to every response.
import FILES from './site-files.js';

const CSP = [
  "default-src 'self'",
  // Inline hash = the one-line boot script that adds the `js` class before first paint.
  "script-src 'self' 'sha256-Du+OJKJSbdUgz5nrHeWWINvez6XKDDU/tyj/5c2uvwo=' https://static.cloudflareinsights.com",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self' https://cloudflareinsights.com",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "object-src 'none'",
  'upgrade-insecure-requests',
].join('; ');

const SECURITY_HEADERS = {
  'Content-Security-Policy': CSP,
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
  'Cross-Origin-Opener-Policy': 'same-origin',
};

// ── Contact form ────────────────────────────────────────────────────────────
const CONTACT_TO = 'hello@quailworks.co';
const CONTACT_FROM = { email: 'website@quailworks.co', name: 'Quailworks website' };
const ALLOWED_ORIGINS = new Set(['https://quailworks.co', 'https://www.quailworks.co']);
const LIMITS = { name: 100, email: 254, company: 120, role: 120, focus: 80, message: 4000 };
const EMAIL_RE = /^[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]{2,}$/;
const FOCUS_OPTIONS = new Set([
  'Outbound pipeline generation',
  'Inbound conversion and routing',
  'CRM data quality and RevOps',
  'AI research and automation',
  "Not sure yet, we'd like an audit",
]);
const MIN_FILL_MS = 3000; // humans take longer than this to fill the form
const URL_RE = /(https?:\/\/|www\.)\S+/gi;
// Strip control characters (incl. CR/LF, which could inject email headers) from single-line fields.
const oneLine = (v) => v.replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim();
const recent = new Map(); // best-effort per-isolate rate limit: ip -> [timestamps]

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...SECURITY_HEADERS },
  });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function rateLimited(ip) {
  const now = Date.now();
  const hits = (recent.get(ip) || []).filter((t) => now - t < 10 * 60 * 1000);
  hits.push(now);
  recent.set(ip, hits);
  if (recent.size > 5000) recent.clear();
  return hits.length > 5;
}

async function handleContact(request, env) {
  const origin = request.headers.get('Origin');
  if (origin && !ALLOWED_ORIGINS.has(origin) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
    return json({ success: false, error: 'Forbidden origin' }, 403);
  }
  if (!(request.headers.get('Content-Type') || '').includes('application/json')) return json({ success: false, error: 'Expected JSON' }, 415);

  if (Number(request.headers.get('Content-Length') || 0) > 20000) return json({ success: false, error: 'Message too large' }, 413);
  const raw = await request.text();
  if (raw.length > 20000) return json({ success: false, error: 'Message too large' }, 413);
  let data;
  try { data = JSON.parse(raw); } catch { return json({ success: false, error: 'Invalid JSON' }, 400); }

  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';

  // Rate limit before doing any work: Cloudflare's rate limiter (per location),
  // plus a per-isolate backstop over a longer window.
  if (env.CONTACT_LIMITER) {
    const { success } = await env.CONTACT_LIMITER.limit({ key: ip });
    if (!success) return json({ success: false, error: 'Too many requests. Please email hello@quailworks.co.' }, 429);
  }
  if (rateLimited(ip)) return json({ success: false, error: 'Too many requests. Please email hello@quailworks.co.' }, 429);

  // Spam traps. Bots get a normal-looking success response and nothing is sent.
  if (data._honey) return json({ success: true });
  const elapsed = Number(data._t);
  if (!Number.isFinite(elapsed) || elapsed < MIN_FILL_MS) return json({ success: true });

  const f = {};
  for (const [key, max] of Object.entries(LIMITS)) f[key] = String(data[key] ?? '').slice(0, max);
  for (const key of ['name', 'email', 'company', 'role', 'focus']) f[key] = oneLine(f[key]);
  f.message = f.message.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '').trim();
  if (!FOCUS_OPTIONS.has(f.focus)) f.focus = '';

  if (!f.name || !f.company || !EMAIL_RE.test(f.email)) {
    return json({ success: false, error: 'Please complete name, work email and company.' }, 422);
  }
  // Links in name/company/role, or a link-stuffed message, are almost always spam.
  const linksInHeaderFields = [f.name, f.company, f.role].some((v) => URL_RE.test(v));
  URL_RE.lastIndex = 0;
  const linkCount = (f.message.match(URL_RE) || []).length;
  if (linksInHeaderFields || linkCount > 2) return json({ success: true });

  const rows = [['Name', f.name], ['Email', f.email], ['Company', f.company], ['Role', f.role || '—'], ['Wants to fix', f.focus || '—']];
  const text = rows.map(([k, v]) => `${k}: ${v}`).join('\n') + `\n\nMessage:\n${f.message || '—'}\n\nReply directly to this email to respond to ${f.name}.`;
  const html = `<table cellpadding="6" style="font-family:Arial,sans-serif;font-size:14px;border-collapse:collapse">${rows
    .map(([k, v]) => `<tr><td style="color:#6B6A64;padding-right:16px">${k}</td><td><strong>${esc(v)}</strong></td></tr>`)
    .join('')}</table><p style="font-family:Arial,sans-serif;font-size:14px;white-space:pre-wrap">${esc(f.message || '—')}</p><p style="font-family:Arial,sans-serif;font-size:12px;color:#6B6A64">Sent from the contact form on quailworks.co. Reply to respond to ${esc(f.name)}.</p>`;

  try {
    await env.EMAIL.send({
      to: CONTACT_TO,
      from: CONTACT_FROM,
      replyTo: { email: f.email, name: f.name },
      subject: `New enquiry: ${f.company}${f.focus ? ' — ' + f.focus : ''}`,
      text,
      html,
    });
    return json({ success: true });
  } catch (err) {
    console.error('contact send failed', err && err.code, err && err.message);
    return json({ success: false, error: 'Could not send right now' }, 502);
  }
}

// Decode once per isolate.
const ASSETS = new Map(
  Object.entries(FILES).map(([path, f]) => [path, { type: f.type, etag: f.etag, body: Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0)) }]),
);

function resolve(pathname) {
  let p = decodeURIComponent(pathname);
  if (p.endsWith('/')) p += 'index.html';
  if (ASSETS.has(p)) return p;
  if (ASSETS.has(p + '.html')) return p + '.html';
  return null;
}

function cacheControl(path) {
  if (path.startsWith('/assets/fonts/')) return 'public, max-age=31536000, immutable';
  if (path.endsWith('.html')) return 'public, max-age=0, must-revalidate';
  return 'public, max-age=3600, must-revalidate';
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.hostname.startsWith('www.')) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }
    if (url.pathname === '/api/contact') {
      if (request.method !== 'POST') return json({ success: false, error: 'Method not allowed' }, 405);
      return handleContact(request, env);
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD', ...SECURITY_HEADERS } });
    }

    const path = resolve(url.pathname);
    const asset = ASSETS.get(path || '/404.html');
    const status = path ? 200 : 404;
    const headers = new Headers({ 'Content-Type': asset.type, 'Cache-Control': cacheControl(path || '/404.html'), ...SECURITY_HEADERS });
    if (path) headers.set('ETag', asset.etag);

    if (path && request.headers.get('If-None-Match') === asset.etag) {
      return new Response(null, { status: 304, headers });
    }
    return new Response(request.method === 'HEAD' ? null : asset.body, { status, headers });
  },
};
