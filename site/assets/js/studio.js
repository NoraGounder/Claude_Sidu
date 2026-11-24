/* Quailworks studio theme: local clock, top bar on scroll. The hero object lives in hero.js.
   The hero object is drawn on a 2D canvas from a 3D tube swept along a curve:
   data-shape="knot" (a torus knot: the engine) or "coil" (a coil-over spring: engineering).
   Lines are shaded by depth and by a rim term, so edges facing away glow in the accent colour. */
(function () {
  'use strict';
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Local time in Warsaw, as on the founder's desk ---------------------------------------- */
  var clock = document.getElementById('clock');
  if (clock && window.Intl) {
    var fmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Warsaw' });
    var tick = function () { clock.textContent = 'WAW ' + fmt.format(new Date()); };
    tick();
    setInterval(tick, 30000);
  }

  /* Top bar gets a backdrop once the hero has scrolled away -------------------------------- */
  var nav = document.getElementById('nav');
  if (nav) {
    var onScroll = function () { nav.classList.toggle('scrolled', window.scrollY > window.innerHeight * 0.6); };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }
})();
