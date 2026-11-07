// Edge entry point for quailworks.co.
// Redirects www to the apex domain, serves the site packed from ./site
// (see scripts/build.mjs), and attaches security headers to every response.
import FILES from './site-files.js';

const CSP = [
  "default-src 'self'",
  // Inline hash = the one-line boot script that adds the `js` class before first paint.
  "script-src 'self' 'sha256-Du+OJKJSbdUgz5nrHeWWINvez6XKDDU/tyj/5c2uvwo=' https://static.cloudflareinsights.com",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self' https://formsubmit.co https://cloudflareinsights.com",
  "form-action 'self' https://formsubmit.co",
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
  async fetch(request) {
    const url = new URL(request.url);

    if (url.hostname.startsWith('www.')) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
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
