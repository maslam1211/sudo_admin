/**
 * How SudoTag Works — clarity layout.
 * Standalone (no main.js — avoids AOS breakage from GLightbox/Swiper).
 */
(function () {
  'use strict';

  function hidePreloader() {
    if (typeof window.sudoDismissPreloader === 'function') {
      window.sudoDismissPreloader();
      return;
    }
    var preloader = document.querySelector('#preloader');
    if (!preloader || preloader.dataset.dismissing === '1') return;
    preloader.dataset.dismissing = '1';
    if (window.__sudoPreloaderLottie) {
      try {
        window.__sudoPreloaderLottie.destroy();
      } catch (e) {}
      window.__sudoPreloaderLottie = null;
    }
    preloader.style.opacity = '0';
    preloader.style.visibility = 'hidden';
    document.body.classList.remove('preloader-active');
    document.documentElement.classList.remove('preloader-pending');
    window.setTimeout(function () {
      if (preloader.parentNode) preloader.remove();
    }, 450);
  }

  if (document.readyState === 'complete') {
    hidePreloader();
  } else {
    window.addEventListener('load', hidePreloader);
    window.setTimeout(hidePreloader, 8000);
  }

  function toggleScrolled() {
    var body = document.querySelector('body');
    var header = document.querySelector('#header');
    if (!body || !header) return;
    if (
      !header.classList.contains('scroll-up-sticky') &&
      !header.classList.contains('sticky-top') &&
      !header.classList.contains('fixed-top')
    ) {
      return;
    }
    if (window.scrollY > 100) body.classList.add('scrolled');
    else body.classList.remove('scrolled');
  }

  document.addEventListener('scroll', toggleScrolled, { passive: true });
  window.addEventListener('load', toggleScrolled);

  var mobileNavToggleBtn = document.querySelector('.mobile-nav-toggle');
  function mobileNavToggle() {
    document.querySelector('body').classList.toggle('mobile-nav-active');
    if (mobileNavToggleBtn) {
      mobileNavToggleBtn.classList.toggle('bi-list');
      mobileNavToggleBtn.classList.toggle('bi-x');
    }
  }
  if (mobileNavToggleBtn) {
    mobileNavToggleBtn.addEventListener('click', mobileNavToggle);
    mobileNavToggleBtn.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        mobileNavToggle();
      }
    });
  }

  document.querySelectorAll('#navmenu a').forEach(function (link) {
    link.addEventListener('click', function () {
      if (document.querySelector('.mobile-nav-active')) mobileNavToggle();
    });
  });

  var scrollTop = document.querySelector('.scroll-top');
  function toggleScrollTop() {
    if (!scrollTop) return;
    if (window.scrollY > 100) scrollTop.classList.add('active');
    else scrollTop.classList.remove('active');
  }
  if (scrollTop) {
    scrollTop.addEventListener('click', function (e) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
  document.addEventListener('scroll', toggleScrollTop, { passive: true });
  window.addEventListener('load', toggleScrollTop);

  function initAOS() {
    if (typeof AOS === 'undefined') {
      document.body.classList.add('hiw-aos-fallback');
      return;
    }
    try {
      AOS.init({
        duration: 550,
        easing: 'ease-out-cubic',
        once: true,
        mirror: false,
        offset: 36,
        startEvent: 'DOMContentLoaded',
      });
      document.body.classList.add('hiw-aos-ready');
      if (typeof AOS.refresh === 'function') {
        window.addEventListener('load', function () {
          AOS.refresh();
        });
      }
    } catch (err) {
      document.body.classList.add('hiw-aos-fallback');
    }
  }

  function initStepProgress() {
    var track = document.querySelector('[data-cl-track]');
    var progress = document.querySelector('[data-cl-progress]');
    var steps = Array.prototype.slice.call(document.querySelectorAll('[data-cl-step]'));
    if (!track || !steps.length) return;

    function update() {
      var rect = track.getBoundingClientRect();
      var viewH = window.innerHeight || document.documentElement.clientHeight;
      var start = viewH * 0.8;
      var end = viewH * 0.2;
      var total = rect.height + (start - end);
      var traveled = start - rect.top;
      var ratio = total > 0 ? traveled / total : 0;
      if (ratio < 0) ratio = 0;
      if (ratio > 1) ratio = 1;

      if (progress) progress.style.height = Math.round(ratio * 100) + '%';

      steps.forEach(function (step) {
        var r = step.getBoundingClientRect();
        var mid = r.top + r.height * 0.4;
        var on = mid < viewH * 0.7 && r.bottom > viewH * 0.15;
        step.classList.toggle('is-active', on);
      });
    }

    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        update();
        ticking = false;
      });
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    update();
  }

  function boot() {
    initAOS();
    initStepProgress();
    window.setTimeout(function () {
      if (!document.body.classList.contains('hiw-aos-ready')) {
        document.body.classList.add('hiw-aos-fallback');
      }
    }, 2500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
