/* Quailworks studio theme: the hero object, 2D line fallback for browsers without WebGL (hero-gl.js).
   Drawn from a 3D tube swept along a curve: data-shape="knot" or "coil". */
(function () {
  'use strict';
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Hero object ---------------------------------------------------------------------------- */
  var canvas = document.querySelector('.hero-canvas');
  if (!canvas || !canvas.getContext || canvas.getAttribute('data-renderer') === 'webgl') return;   // WebGL version runs
  var ctx = canvas.getContext('2d');
  if (!ctx) return;
  var shape = canvas.getAttribute('data-shape') || 'knot';

  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function norm(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }

  // Sweep a circle of radius r along curve(t), t in [0, 1]; returns rings of [point, outward normal].
  function tube(curve, samples, sides, r, closed) {
    var rings = [], prevN = null;
    for (var i = 0; i <= samples; i++) {
      var t = i / samples, e = 1 / samples;
      var c = curve(t), T = norm(sub(curve(Math.min(1, t + e)), curve(Math.max(0, t - e))));
      var N = prevN ? norm(cross(cross(T, prevN), T)) : norm(cross(T, Math.abs(T[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]));
      var B = cross(T, N);
      prevN = N;
      var ring = [];
      for (var k = 0; k < sides; k++) {
        var a = (k / sides) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
        var n = [N[0] * ca + B[0] * sa, N[1] * ca + B[1] * sa, N[2] * ca + B[2] * sa];
        ring.push([[c[0] + n[0] * r, c[1] + n[1] * r, c[2] + n[2] * r], n]);
      }
      rings.push(ring);
    }
    if (closed) rings[rings.length - 1] = rings[0];
    return rings;
  }

  var parts = [];
  if (shape === 'coil') {
    // A coil spring around a damper body: seven turns, tilted, turning slowly.
    var turns = 7, R = 0.62, H = 2.3;
    parts.push({ rings: tube(function (t) {
      var a = t * turns * Math.PI * 2;
      return [R * Math.cos(a), -H / 2 + t * H, R * Math.sin(a)];
    }, 560, 10, 0.085, false), every: 0 });
    parts.push({ rings: tube(function (t) { return [0, -H / 2 - 0.35 + t * (H + 0.7), 0]; }, 40, 18, 0.24, false), every: 8, faint: true });
    [-H / 2 - 0.02, H / 2 + 0.02].forEach(function (y) {
      parts.push({ rings: tube(function (t) { var a = t * Math.PI * 2; return [0.78 * Math.cos(a), y, 0.78 * Math.sin(a)]; }, 90, 6, 0.05, true), every: 0 });
    });
  } else {
    // A (2,3) torus knot: one continuous line that keeps coming back on itself.
    parts.push({ rings: tube(function (t) {
      var a = t * Math.PI * 2, p = 2, q = 3, r = 0.42 * Math.cos(q * a) + 0.95;
      return [r * Math.cos(p * a), r * Math.sin(p * a), -0.42 * Math.sin(q * a)];
    }, 620, 14, 0.2, true), every: 0 });
  }

  var W = 0, Hh = 0, dpr = 1, cx = 0, cy = 0, scale = 1;
  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth; Hh = canvas.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(Hh * dpr);
    var narrow = W < 860;
    cx = W * (narrow ? 0.62 : 0.45); cy = Hh * (narrow ? 0.36 : 0.46);
    scale = Math.min(W, Hh) * (shape === 'coil' ? (narrow ? 0.3 : 0.22) : (narrow ? 0.4 : 0.27));
  }

  var mx = 0, my = 0, tx = 0, ty = 0;
  window.addEventListener('pointermove', function (e) {
    tx = (e.clientX / window.innerWidth - 0.5); ty = (e.clientY / window.innerHeight - 0.5);
  }, { passive: true });

  var BUCKETS = 10, paths = [];
  function draw(time) {
    mx += (tx - mx) * 0.04; my += (ty - my) * 0.04;
    var yaw = time * 0.00018 + mx * 0.6, pitch = (shape === 'coil' ? 0.38 : 0.55) + my * 0.35;
    var roll = shape === 'coil' ? -0.42 : time * 0.00006;
    var cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
    function rot(v) {
      var x = v[0] * cyw + v[2] * syw, z = -v[0] * syw + v[2] * cyw, y = v[1];
      var y2 = y * cp - z * sp, z2 = y * sp + z * cp;
      return [x * cr - y2 * sr, x * sr + y2 * cr, z2];
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, Hh);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    for (var b = 0; b < BUCKETS; b++) paths[b] = new Path2D();
    var cam = 4.2;
    parts.forEach(function (part) {
      var proj = part.rings.map(function (ring) {
        return ring.map(function (pn) {
          var p = rot(pn[0]), n = rot(pn[1]);
          var f = cam / (cam - p[2]);
          // rim: 1 at silhouette edges, 0 facing the viewer; depth: 0 far .. 1 near
          var rim = 1 - Math.abs(n[2]), depth = Math.max(0, Math.min(1, (p[2] + 1.6) / 3.2));
          return [cx + p[0] * scale * f, cy - p[1] * scale * f, rim * rim * (0.35 + 0.65 * depth), depth];
        });
      });
      var sides = proj[0].length;
      for (var i = 1; i < proj.length; i++) {
        for (var k = 0; k < sides; k++) {
          var a = proj[i - 1][k], c = proj[i][k];
          var v = (a[2] + c[2]) * 0.5 * (part.faint ? 0.35 : 1);
          var bk = Math.min(BUCKETS - 1, Math.floor(v * BUCKETS));
          paths[bk].moveTo(a[0], a[1]); paths[bk].lineTo(c[0], c[1]);
          if (part.every && i % part.every === 0) {
            var d = proj[i][(k + 1) % sides];
            paths[bk].moveTo(c[0], c[1]); paths[bk].lineTo(d[0], d[1]);
          }
        }
      }
    });
    for (var j = 0; j < BUCKETS; j++) {
      var v = (j + 0.5) / BUCKETS;
      // dim white in the body, warming to the accent at the rim
      var r = 255, g = Math.round(235 - 140 * v), bl = Math.round(225 - 205 * v);
      ctx.strokeStyle = 'rgba(' + r + ',' + g + ',' + bl + ',' + (0.05 + 0.6 * v).toFixed(3) + ')';
      ctx.lineWidth = 0.6 + 1.1 * v;
      ctx.stroke(paths[j]);
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  var running = false, visible = true, raf = 0;
  function loop(t) { draw(t); raf = running ? requestAnimationFrame(loop) : 0; }
  function setRunning(on) {
    on = on && visible && !document.hidden && !reduceMotion;
    if (on && !running) { running = true; raf = requestAnimationFrame(loop); }
    if (!on) { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; }
  }
  resize();
  draw(2600);
  window.addEventListener('resize', function () { resize(); if (!running) draw(2600); });
  document.addEventListener('visibilitychange', function () { setRunning(true); });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; setRunning(true); }).observe(canvas);
  }
  setRunning(true);
})();
