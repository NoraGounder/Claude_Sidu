/* Quailworks — site behaviour */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var CONTACT_EMAIL = 'hello@quailworks.co';

  /* Year ------------------------------------------------------------------ */
  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();

  /* Mobile menu ----------------------------------------------------------- */
  var nav = document.getElementById('nav');
  var menuBtn = nav && nav.querySelector('.menu-btn');
  function setMenu(open) {
    nav.classList.toggle('open', open);
    menuBtn.setAttribute('aria-expanded', String(open));
    menuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }
  if (menuBtn) {
    menuBtn.addEventListener('click', function () { setMenu(!nav.classList.contains('open')); });
    nav.querySelectorAll('.mobile-menu a').forEach(function (a) {
      a.addEventListener('click', function () { setMenu(false); });
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setMenu(false); });
  }

  /* Scroll reveal --------------------------------------------------------- */
  var reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { entry.target.classList.add('in'); io.unobserve(entry.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add('in'); });
  }

  /* Hero console ---------------------------------------------------------- */
  var CHECK = '<span class="check"><svg viewBox="0 0 12 12" fill="none"><path d="M2.5 6.2l2.3 2.3 4.7-4.8" stroke="#4CC38A" stroke-width="1.6"/></svg></span>';
  var scenarios = [
    {
      type: 'Job change', text: 'Former champion <b>Dana Okafor</b> joined Northwind Freight as VP Sales',
      name: 'Northwind Freight', meta: 'Logistics · 1,200 employees · Series C', tier: 'Tier 1', scores: [92, 81, 88],
      people: [['DO', 'Dana Okafor', 'VP Sales · former champion'], ['LO', 'Luis Ortega', 'Head of Revenue Operations'], ['PN', 'Priya Nair', 'Chief Financial Officer']],
      play: 'Champion moved',
      actions: ['Enriched through a 3-provider waterfall', 'Scored against your closed-won model', 'Routed to <b>Maya Rivera</b>, AE West', 'Warm intro drafted for rep review', 'LinkedIn touch queued', 'Salesforce opportunity created', 'Alert posted to <b>#pipeline-west</b>']
    },
    {
      type: 'Hiring', text: '<b>Contoso Analytics</b> opened 6 SDR roles in Chicago',
      name: 'Contoso Analytics', meta: 'B2B software · 480 employees · Series B', tier: 'Tier 1', scores: [88, 74, 91],
      people: [['SW', 'Sam Whitfield', 'Chief Revenue Officer'], ['AB', 'Aisha Bello', 'Director, Sales Operations'], ['TB', 'Tom Brandt', 'Head of Sales Development']],
      play: 'Scaling a sales team',
      actions: ['Enriched through a 3-provider waterfall', 'Scored against your closed-won model', 'Routed to <b>Jordan Lee</b>, AE Mid-market', '3-step sequence drafted for review', 'LinkedIn touch queued', 'HubSpot deal created', 'Alert posted to <b>#pipeline-mm</b>']
    },
    {
      type: 'Web intent', text: '<b>Fabrikam Payments</b> viewed /pricing three times this week',
      name: 'Fabrikam Payments', meta: 'Fintech · 2,300 employees · Public', tier: 'Tier 1', scores: [84, 95, 77],
      people: [['EH', 'Elena Hart', 'SVP Sales'], ['RK', 'Raj Kapoor', 'VP Revenue Operations'], ['MC', 'Mei Chen', 'Director, Procurement']],
      play: 'High-intent visit',
      actions: ['Website visit resolved to account', 'Scored against your closed-won model', 'Routed to <b>Chris Park</b>, Enterprise AE', 'Meeting brief generated for the AE', 'Retargeting audience updated', 'Salesforce activity logged', 'Alert posted to <b>#enterprise-deals</b>']
    },
    {
      type: 'Funding', text: '<b>Tailspin Health</b> announced a $60M Series C',
      name: 'Tailspin Health', meta: 'Healthtech · 900 employees · Series C', tier: 'Tier 2', scores: [79, 68, 94],
      people: [['NA', 'Noah Adams', 'Chief Operating Officer'], ['GL', 'Grace Liu', 'VP Sales'], ['OB', 'Omar Baker', 'Head of Growth']],
      play: 'Fresh funding',
      actions: ['Enriched through a 3-provider waterfall', 'Scored against your closed-won model', 'Routed to <b>Maya Rivera</b>, AE West', 'Congratulations note drafted for review', 'Added to executive nurture track', 'Salesforce account updated', 'Alert posted to <b>#pipeline-west</b>']
    }
  ];
  var TIMES = ['just now', '4m ago', '11m ago', '26m ago'];

  var signalsEl = document.getElementById('signals');
  var consoleEl = document.querySelector('.console');
  if (signalsEl && consoleEl) {
    var accountPane = document.querySelector('.pane-account');
    var nameEl = document.getElementById('acct-name');
    var metaEl = document.getElementById('acct-meta');
    var tierEl = document.getElementById('acct-tier');
    var peopleEl = document.getElementById('people');
    var playEl = document.getElementById('play-name');
    var actionsEl = document.getElementById('actions');
    var bars = consoleEl.querySelectorAll('.score');

    // Tag the initial list so duplicates can be replaced.
    var keyOrder = [0, 2, 1, 3];
    Array.prototype.forEach.call(signalsEl.children, function (li, i) { li.setAttribute('data-k', keyOrder[i]); });

    var current = 0;
    var visible = false;
    var timers = [];
    function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
    function clearTimers() { timers.forEach(clearTimeout); timers = []; }

    function renderSignal(k) {
      var s = scenarios[k];
      var old = signalsEl.querySelector('[data-k="' + k + '"]');
      if (old) old.remove();
      var li = document.createElement('li');
      li.className = 'sig enter';
      li.setAttribute('data-k', k);
      li.innerHTML = '<span class="sig-type">' + s.type + '</span><span class="sig-time"></span><span class="sig-text">' + s.text + '</span>';
      signalsEl.insertBefore(li, signalsEl.firstChild);
      while (signalsEl.children.length > 4) signalsEl.removeChild(signalsEl.lastChild);
      Array.prototype.forEach.call(signalsEl.children, function (el, i) {
        el.classList.toggle('active', i === 0);
        el.querySelector('.sig-time').textContent = TIMES[i];
      });
    }

    function renderAccount(k) {
      var s = scenarios[k];
      accountPane.classList.add('fading');
      later(function () {
        nameEl.textContent = s.name;
        metaEl.textContent = s.meta;
        tierEl.textContent = s.tier;
        playEl.textContent = s.play;
        bars.forEach(function (row, i) {
          row.querySelector('.bar i').style.width = s.scores[i] + '%';
          row.querySelector('b').textContent = s.scores[i];
        });
        peopleEl.innerHTML = s.people.map(function (p) {
          return '<li class="person"><span class="avatar">' + p[0] + '</span><div><b>' + p[1] + '</b><small>' + p[2] + '</small></div><span class="verified">✓ verified</span></li>';
        }).join('');
        actionsEl.innerHTML = s.actions.map(function (a) {
          return '<li class="act">' + CHECK + '<span>' + a + '</span></li>';
        }).join('');
        accountPane.classList.remove('fading');
        var items = actionsEl.children;
        Array.prototype.forEach.call(items, function (el, i) {
          later(function () { el.classList.add('done'); }, 500 + i * 430);
        });
      }, 320);
    }

    function step() {
      if (!visible || document.hidden) return;
      current = (current + 1) % scenarios.length;
      renderSignal(current);
      renderAccount(current);
      later(step, 7200);
    }

    if (!reduceMotion && 'IntersectionObserver' in window) {
      var cio = new IntersectionObserver(function (entries) {
        var nowVisible = entries[0].isIntersecting;
        if (nowVisible && !visible) { visible = true; clearTimers(); later(step, 4200); }
        if (!nowVisible && visible) { visible = false; clearTimers(); }
      }, { threshold: 0.25 });
      cio.observe(consoleEl);
      document.addEventListener('visibilitychange', function () {
        clearTimers();
        if (!document.hidden && visible) later(step, 2500);
      });
    }
  }

  /* Contact form ---------------------------------------------------------- */
  var form = document.getElementById('contact-form');
  if (form) {
    var status = document.getElementById('form-status');
    var submit = form.querySelector('button[type="submit"]');
    var submitLabel = submit.innerHTML;

    function showStatus(html, isError) {
      status.innerHTML = html;
      status.classList.add('show');
      status.classList.toggle('err', !!isError);
    }

    function mailtoFrom(data) {
      var body = 'Name: ' + data.name + '\nCompany: ' + data.company + '\nRole: ' + (data.role || '-') +
        '\nFocus: ' + data.focus + '\n\n' + (data.message || '');
      return 'mailto:' + CONTACT_EMAIL + '?subject=' + encodeURIComponent('Consultation request — ' + data.company) +
        '&body=' + encodeURIComponent(body);
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var fields = form.querySelectorAll('[required]');
      var firstBad = null;
      fields.forEach(function (input) {
        var ok = input.value.trim() !== '' && (input.type !== 'email' || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value.trim()));
        input.closest('.field').classList.toggle('invalid', !ok);
        input.setAttribute('aria-invalid', String(!ok));
        if (!ok && !firstBad) firstBad = input;
      });
      if (firstBad) {
        showStatus('Please complete the highlighted fields.', true);
        firstBad.focus();
        return;
      }

      var data = {};
      new FormData(form).forEach(function (v, k) { data[k] = typeof v === 'string' ? v.trim() : v; });
      if (data._honey) { showStatus('Thank you. We will be in touch shortly.'); form.reset(); return; }

      submit.disabled = true;
      submit.textContent = 'Sending…';

      fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(data)
      })
        .then(function (res) { return res.json().then(function (json) { return { ok: res.ok, json: json }; }); })
        .then(function (r) {
          if (r.ok && (r.json.success === true || r.json.success === 'true')) {
            showStatus('<b>Thank you, ' + escapeHtml(data.name.split(' ')[0]) + '.</b> Your request is in. We reply within one business day.');
            form.reset();
          } else {
            throw new Error((r.json && r.json.message) || 'Submission failed');
          }
        })
        .catch(function () {
          showStatus('We couldn\'t send that automatically. <a href="' + mailtoFrom(data) + '">Send it by email instead</a>. Your message is already filled in.', true);
        })
        .then(function () {
          submit.disabled = false;
          submit.innerHTML = submitLabel;
        });
    });

    form.querySelectorAll('input, select, textarea').forEach(function (el) {
      el.addEventListener('input', function () {
        var f = el.closest('.field');
        if (f && f.classList.contains('invalid')) { f.classList.remove('invalid'); el.removeAttribute('aria-invalid'); }
      });
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
})();
