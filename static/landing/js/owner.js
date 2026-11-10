/* SudoTag landing — owner page interactions (no framework). */
(function () {
  'use strict';

  var doc = document.documentElement;
  var body = document.body;
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Header state + progress bar + mobile dock ---------- */
  var header = document.getElementById('stHeader');
  var progress = document.getElementById('stProgress');
  var dock = document.getElementById('stDock');
  var hero = document.getElementById('hero');
  var ticking = false;

  function onScroll() {
    var y = window.scrollY || window.pageYOffset;
    if (header) header.classList.toggle('is-scrolled', y > 24);
    if (progress) {
      var max = doc.scrollHeight - window.innerHeight;
      progress.style.transform = 'scaleX(' + (max > 0 ? Math.min(1, y / max) : 0) + ')';
    }
    if (dock && hero) {
      var show = y > hero.offsetHeight * 0.75;
      dock.classList.toggle('is-visible', show);
      dock.setAttribute('aria-hidden', show ? 'false' : 'true');
      dock.querySelectorAll('a').forEach(function (a) { a.tabIndex = show ? 0 : -1; });
    }
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(onScroll); }
  }, { passive: true });
  onScroll();

  /* ---------- Mobile menu ---------- */
  var burger = document.getElementById('stBurger');
  var nav = document.getElementById('stNav');
  function setMenu(open) {
    body.classList.toggle('st-nav-open', open);
    if (burger) {
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
      burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    }
  }
  if (burger) {
    burger.addEventListener('click', function () { setMenu(!body.classList.contains('st-nav-open')); });
  }
  if (nav) {
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setMenu(false); });

  /* ---------- Scroll spy for nav ---------- */
  var navLinks = nav ? Array.prototype.slice.call(nav.querySelectorAll('a[href^="#"]')) : [];
  if ('IntersectionObserver' in window && navLinks.length) {
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        navLinks.forEach(function (a) {
          a.classList.toggle('is-active', a.getAttribute('href') === '#' + entry.target.id);
        });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    navLinks.forEach(function (a) {
      var target = document.querySelector(a.getAttribute('href'));
      if (target) spy.observe(target);
    });
  }

  /* ---------- Reveal on scroll ---------- */
  var reveals = document.querySelectorAll('.st-reveal');
  if (reduceMotion || !('IntersectionObserver' in window)) {
    reveals.forEach(function (el) { el.classList.add('is-in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in');
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  /* ---------- Hero plate: type out different registrations ---------- */
  var plateEl = document.querySelector('.st-plate__num[data-plates]');
  if (plateEl && !reduceMotion) {
    var plates;
    try { plates = JSON.parse(plateEl.getAttribute('data-plates')) || []; } catch (e) { plates = []; }
    var idx = 0;
    var typeTimer = null;

    function typePlate(text, done) {
      var i = 0;
      plateEl.classList.add('is-typing');
      plateEl.textContent = '';
      (function step() {
        plateEl.textContent = text.slice(0, i);
        if (i++ < text.length) {
          typeTimer = window.setTimeout(step, text.charAt(i - 1) === ' ' ? 40 : 85);
        } else {
          plateEl.classList.remove('is-typing');
          done();
        }
      })();
    }
    function cycle() {
      idx = (idx + 1) % plates.length;
      typePlate(plates[idx], function () { typeTimer = window.setTimeout(cycle, 12000 - 1400); });
    }
    if (plates.length > 1) {
      // Swap plate once per 12s story loop, just before the next scan starts.
      typeTimer = window.setTimeout(cycle, 11000);
    }
    document.addEventListener('visibilitychange', function () {
      if (document.hidden && typeTimer) { window.clearTimeout(typeTimer); typeTimer = null; }
      else if (!document.hidden && !typeTimer && plates.length > 1) { typeTimer = window.setTimeout(cycle, 3000); }
    });
  }

  /* ---------- Offers slider (Swiper, config from inline JSON) ---------- */
  function initSwipers() {
    if (typeof window.Swiper === 'undefined') return;
    document.querySelectorAll('.init-swiper').forEach(function (el) {
      var cfgNode = el.querySelector('.swiper-config');
      var cfg = {};
      try { cfg = JSON.parse(cfgNode ? cfgNode.textContent : '{}'); } catch (e) {}
      if (reduceMotion) { delete cfg.autoplay; }
      // eslint-disable-next-line no-new
      new window.Swiper(el, cfg);
    });
  }
  if (document.readyState === 'complete') initSwipers();
  else window.addEventListener('load', initSwipers);

  /* ---------- Links that open a specific scanner tab ---------- */
  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-scan-tab]');
    if (!link) return;
    var tab = document.querySelector('.find-vehicle-tab[data-tab="' + link.getAttribute('data-scan-tab') + '"]');
    if (tab && !tab.classList.contains('is-active')) tab.click();
  });
})();
