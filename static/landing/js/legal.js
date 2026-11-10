/* SudoTag legal pages: table-of-contents scroll-spy + reading progress. */
(function () {
  'use strict';
  var doc = document.getElementById('lgDoc'); if (!doc) return;
  var links = Array.prototype.slice.call(document.querySelectorAll('[data-toc-link]'));
  var secs = links.map(function (a) { return document.querySelector(a.getAttribute('href')); });
  var bar = document.getElementById('lgRead'), toc = document.querySelector('.lg-toc ol'), cur = -1, ticking = false;
  var mobile = window.matchMedia('(max-width: 1023px)');

  function update() {
    ticking = false;
    var line = window.innerHeight * .3, idx = 0;
    secs.forEach(function (s, i) { if (s && s.getBoundingClientRect().top < line) idx = i; });
    if (idx !== cur) {
      cur = idx;
      links.forEach(function (a, i) { a.classList.toggle('is-on', i === idx); a.setAttribute('aria-current', i === idx ? 'true' : 'false'); });
      /* keep the active chip in view on the mobile chip bar */
      if (mobile.matches && toc && links[idx]) {
        var li = links[idx].parentNode;
        toc.scrollTo({ left: li.offsetLeft - 16, behavior: 'smooth' });
      }
    }
    if (bar) {
      var r = doc.getBoundingClientRect(), total = r.height - window.innerHeight * .6;
      bar.style.width = Math.max(0, Math.min(1, -r.top / (total || 1))) * 100 + '%';
    }
  }
  window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  window.addEventListener('resize', update);
  update();
})();
