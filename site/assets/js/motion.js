/* Motion layer (see assets/css/motion.css): written by Qwen 4 Max through OpenRouter on 2026-11-24, reviewed and
   integrated by Claude. Pointer effects only on fine pointers; reduced motion gets plain fades. */
/* quailworks motion layer — dependency-free, CSP-safe (classes + custom props only) */
(() => {
  'use strict';
  const d = document;
  const $$ = (s, c = d) => [...c.querySelectorAll(s)];
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;

  /* 6 · scroll progress */
  const bar = d.createElement('div');
  bar.className = 'qw-progress';
  bar.setAttribute('aria-hidden', 'true');
  d.body.appendChild(bar);
  let queued = false;
  const paintBar = () => {
    queued = false;
    const max = d.documentElement.scrollHeight - innerHeight;
    bar.style.setProperty('--sp', max > 0 ? clamp(scrollY / max, 0, 1).toFixed(4) : 0);
  };
  addEventListener('scroll', () => {
    if (!queued) { queued = true; requestAnimationFrame(paintBar); }
  }, { passive: true });
  addEventListener('resize', paintBar, { passive: true });
  paintBar();

  /* 1 · headline word split (preserves <em>, <br>, .dot; a11y via aria-label) */
  const splitHeading = (h) => {
    const clone = h.cloneNode(true);
    $$('br', clone).forEach(b => b.replaceWith(' '));
    const label = clone.textContent.replace(/\s+/g, ' ').trim();
    if (label) h.setAttribute('aria-label', label);
    const words = [];
    const wrapText = (text, parent, ref) => {
      const frag = d.createDocumentFragment();
      text.split(/(\s+)/).forEach(part => {
        if (!part) return;
        if (/^\s+$/.test(part)) { frag.appendChild(d.createTextNode(part)); return; }
        const w = d.createElement('span');
        w.className = 'w';
        w.setAttribute('aria-hidden', 'true');
        const i = d.createElement('span');
        i.className = 'wi';
        i.textContent = part;
        w.appendChild(i);
        frag.appendChild(w);
        words.push(w);
      });
      parent.insertBefore(frag, ref);
    };
    const walk = (node) => {
      [...node.childNodes].forEach(n => {
        if (n.nodeType === 3) { wrapText(n.textContent, node, n); n.remove(); }
        else if (n.nodeType === 1 && n.tagName !== 'BR') {
          if (n.classList.contains('dot')) {
            const i = d.createElement('span');
            i.className = 'wi';
            while (n.firstChild) i.appendChild(n.firstChild);
            n.appendChild(i);
            n.classList.add('w');
            n.setAttribute('aria-hidden', 'true');
            words.push(n);
          } else walk(n);
        }
      });
    };
    walk(h);
    words.forEach((el, i) => el.style.setProperty('--i', Math.min(i, 14)));
    h.classList.add('wsplit');
  };
  if (!reduced) {
    const heads = $$('h1.display, h2.display');
    heads.forEach(splitHeading);
    const io = new IntersectionObserver(entries => entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
    }), { threshold: 0.2, rootMargin: '0px 0px -8% 0px' });
    heads.forEach(h => io.observe(h)); /* existing .reveal observer keeps working */
  }

  /* 2 + 3 · magnetic pull and card spotlight — fine pointers only */
  if (fine && !reduced) {
    $$('.chip, .btn').forEach(el => {
      let r = null;
      el.addEventListener('pointerenter', () => { r = el.getBoundingClientRect(); });
      el.addEventListener('pointermove', e => {
        if (!r) r = el.getBoundingClientRect();
        const tx = clamp((e.clientX - r.left - r.width / 2) / r.width * 12, -6, 6);
        const ty = clamp((e.clientY - r.top - r.height / 2) / r.height * 12, -6, 6);
        el.style.setProperty('--tx', tx.toFixed(2) + 'px');
        el.style.setProperty('--ty', ty.toFixed(2) + 'px');
      });
      el.addEventListener('pointerleave', () => {
        r = null;
        el.style.setProperty('--tx', '0px');
        el.style.setProperty('--ty', '0px');
      });
    });
    $$('.svc, .plan').forEach(card => {
      card.addEventListener('pointermove', e => {
        const r = card.getBoundingClientRect();
        card.style.setProperty('--mx', (e.clientX - r.left).toFixed(1) + 'px');
        card.style.setProperty('--my', (e.clientY - r.top).toFixed(1) + 'px');
      });
    });
  }

  /* 4 · stats count up once, width reserved to avoid layout shift */
  const fmt = (n, dec) => n.toLocaleString('en-US', {
    minimumFractionDigits: dec, maximumFractionDigits: dec
  });
  const stats = $$('.stat');
  if (!reduced && stats.length) {
    const sio = new IntersectionObserver(entries => entries.forEach(en => {
      if (!en.isIntersecting) return;
      sio.unobserve(en.target);
      const el = en.target.querySelector('.stat-n') ||
        [...en.target.children].find(c => /\d/.test(c.textContent));
      if (!el) return;
      const m = el.textContent.trim().match(/^(\D*?)([\d,]+(?:\.\d+)?)([\s\S]*)$/);
      if (!m) return;
      const [, pre, raw, suf] = m;
      const end = parseFloat(raw.replace(/,/g, ''));
      if (!isFinite(end)) return;
      const dec = (raw.split('.')[1] || '').length;
      el.style.setProperty('--qw-w', el.offsetWidth + 'px');
      el.classList.add('qw-count');
      const t0 = performance.now(), dur = 1400;
      const tick = (t) => {
        const p = clamp((t - t0) / dur, 0, 1);
        const e = 1 - Math.pow(1 - p, 3);
        el.textContent = pre + fmt(end * e, dec) + suf;
        if (p < 1) requestAnimationFrame(tick);
      };
      el.textContent = pre + fmt(0, dec) + suf;
      requestAnimationFrame(tick);
    }), { threshold: 0.5 });
    stats.forEach(s => sio.observe(s));
  }

  /* 5 · stack marquee — wide screens only, seamless duplicated track */
  const stack = d.querySelector('section.stack');
  const list = stack && stack.querySelector('ul, ol');
  if (list && !reduced && matchMedia('(min-width: 900px)').matches) {
    [...list.children].forEach(li => {
      const c = li.cloneNode(true);
      c.setAttribute('aria-hidden', 'true');
      $$('a, button, [tabindex]', c).forEach(f => { f.tabIndex = -1; });
      list.appendChild(c);
    });
    list.classList.add('mq');
    stack.classList.add('qw-mq');
    const half = list.scrollWidth / 2;
    list.style.setProperty('--dur', Math.max(20, half / 45).toFixed(1) + 's');
  }
})();
