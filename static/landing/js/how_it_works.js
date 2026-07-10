/**
 * How SudoTag Works page — standalone init (does not use main.js).
 * main.js requires GLightbox/Swiper/PureCounter and breaks AOS on this page.
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
      try { window.__sudoPreloaderLottie.destroy(); } catch (e) {}
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
    /* Safety: never leave the wheel stuck if load is delayed */
    window.setTimeout(hidePreloader, 4500);
  }

  function toggleScrolled() {
    var body = document.querySelector('body');
    var header = document.querySelector('#header');
    if (!body || !header) return;
    if (!header.classList.contains('scroll-up-sticky') &&
        !header.classList.contains('sticky-top') &&
        !header.classList.contains('fixed-top')) return;
    if (window.scrollY > 100) {
      body.classList.add('scrolled');
    } else {
      body.classList.remove('scrolled');
    }
  }

  document.addEventListener('scroll', toggleScrolled);
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
  }

  document.querySelectorAll('#navmenu a').forEach(function (navmenu) {
    navmenu.addEventListener('click', function () {
      if (document.querySelector('.mobile-nav-active')) {
        mobileNavToggle();
      }
    });
  });

  var scrollTop = document.querySelector('.scroll-top');
  function toggleScrollTop() {
    if (scrollTop) {
      if (window.scrollY > 100) {
        scrollTop.classList.add('active');
      } else {
        scrollTop.classList.remove('active');
      }
    }
  }
  if (scrollTop) {
    scrollTop.addEventListener('click', function (e) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
  document.addEventListener('scroll', toggleScrollTop);
  window.addEventListener('load', toggleScrollTop);

  function initAOS() {
    if (typeof AOS === 'undefined') {
      document.body.classList.add('hiw-aos-fallback');
      return;
    }
    try {
      AOS.init({
        duration: 600,
        easing: 'ease-in-out',
        once: true,
        mirror: false,
        startEvent: 'DOMContentLoaded'
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

  function initTabs() {
    var tabs = document.querySelectorAll('.hiw-paths__tab');
    var panels = document.querySelectorAll('.hiw-paths__panel');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = tab.getAttribute('data-tab');
        tabs.forEach(function (t) {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        panels.forEach(function (p) {
          p.classList.remove('active');
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        var panel = document.getElementById('panel-' + target);
        if (panel) {
          panel.classList.add('active');
        }
        if (typeof AOS !== 'undefined' && typeof AOS.refresh === 'function') {
          setTimeout(function () {
            AOS.refresh();
          }, 50);
        }
      });
    });
  }

  function initSideNav() {
    var sidenavLinks = document.querySelectorAll('.hiw-sidenav a');
    var sections = [];
    sidenavLinks.forEach(function (link) {
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) !== '#') return;
      var id = href.slice(1);
      var el = document.getElementById(id);
      if (el) {
        sections.push({ el: el, link: link });
      }
    });
    if (!sections.length || !('IntersectionObserver' in window)) return;
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            sidenavLinks.forEach(function (l) {
              l.classList.remove('active');
            });
            var match = sections.find(function (s) {
              return s.el === entry.target;
            });
            if (match) {
              match.link.classList.add('active');
            }
          }
        });
      },
      { rootMargin: '-40% 0px -50% 0px', threshold: 0 }
    );
    sections.forEach(function (s) {
      observer.observe(s.el);
    });
  }

  function boot() {
    initAOS();
    initTabs();
    initSideNav();
    /* If AOS never animates (blocked script / slow CDN), show content anyway */
    setTimeout(function () {
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
