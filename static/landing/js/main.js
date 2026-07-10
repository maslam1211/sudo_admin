/**
* Template Name: Gp
* Template URL: https://bootstrapmade.com/gp-free-multipurpose-html-bootstrap-template/
* Updated: Aug 15 2024 with Bootstrap v5.3.3
* Author: BootstrapMade.com
* License: https://bootstrapmade.com/license/
*/

(function() {
  "use strict";

  /**
   * Apply .scrolled class to the body as the page is scrolled down
   */
  function toggleScrolled() {
    const selectBody = document.querySelector('body');
    const selectHeader = document.querySelector('#header');
    if (!selectHeader.classList.contains('scroll-up-sticky') && !selectHeader.classList.contains('sticky-top') && !selectHeader.classList.contains('fixed-top')) return;
    window.scrollY > 100 ? selectBody.classList.add('scrolled') : selectBody.classList.remove('scrolled');
  }

  document.addEventListener('scroll', toggleScrolled);
  window.addEventListener('load', toggleScrolled);

  /**
   * Mobile nav toggle
   */
  const mobileNavToggleBtn = document.querySelector('.mobile-nav-toggle');

  function mobileNavToogle() {
    document.querySelector('body').classList.toggle('mobile-nav-active');
    mobileNavToggleBtn.classList.toggle('bi-list');
    mobileNavToggleBtn.classList.toggle('bi-x');
  }
  if (mobileNavToggleBtn) {
    mobileNavToggleBtn.addEventListener('click', mobileNavToogle);
  }

  /**
   * Hide mobile nav on same-page/hash links
   */
  document.querySelectorAll('#navmenu a').forEach(navmenu => {
    navmenu.addEventListener('click', () => {
      if (document.querySelector('.mobile-nav-active')) {
        mobileNavToogle();
      }
    });

  });

  /**
   * Toggle mobile nav dropdowns
   */
  document.querySelectorAll('.navmenu .toggle-dropdown').forEach(navmenu => {
    navmenu.addEventListener('click', function(e) {
      e.preventDefault();
      this.parentNode.classList.toggle('active');
      this.parentNode.nextElementSibling.classList.toggle('dropdown-active');
      e.stopImmediatePropagation();
    });
  });

  /**
   * Preloader (Lottie wheel.json) — prefer shared dismiss from landing_preloader
   */
  function dismissPreloader() {
    if (typeof window.sudoDismissPreloader === 'function') {
      window.sudoDismissPreloader();
      return;
    }
    const preloader = document.querySelector('#preloader');
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

  const preloader = document.querySelector('#preloader');
  if (preloader) {
    if (document.readyState === 'complete') {
      dismissPreloader();
    } else {
      window.addEventListener('load', dismissPreloader);
      window.setTimeout(dismissPreloader, 8000);
    }
  }

  /**
   * Scroll top button
   */
  let scrollTop = document.querySelector('.scroll-top');

  function toggleScrollTop() {
    if (scrollTop) {
      window.scrollY > 100 ? scrollTop.classList.add('active') : scrollTop.classList.remove('active');
    }
  }
  if (scrollTop) {
    scrollTop.addEventListener('click', (e) => {
      e.preventDefault();
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    });
  }

  window.addEventListener('load', toggleScrollTop);
  document.addEventListener('scroll', toggleScrollTop);

  /**
   * Animation on scroll function and init
   */
  function aosInit() {
    AOS.init({
      duration: 700,
      easing: 'ease-out-cubic',
      once: true,
      mirror: false,
      offset: 60
    });
  }
  window.addEventListener('load', aosInit);

  /**
   * Init swiper sliders
   */
  function initSwiper() {
    document.querySelectorAll(".init-swiper").forEach(function(swiperElement) {
      let config = JSON.parse(
        swiperElement.querySelector(".swiper-config").innerHTML.trim()
      );

      if (swiperElement.classList.contains("swiper-tab")) {
        initSwiperWithCustomPagination(swiperElement, config);
      } else {
        new Swiper(swiperElement, config);
      }
    });
  }

  window.addEventListener("load", initSwiper);

  /**
   * Initiate glightbox
   */
  const glightbox = GLightbox({
    selector: '.glightbox'
  });

  /**
   * Init isotope layout and filters
   */
  document.querySelectorAll('.isotope-layout').forEach(function(isotopeItem) {
    let layout = isotopeItem.getAttribute('data-layout') ?? 'masonry';
    let filter = isotopeItem.getAttribute('data-default-filter') ?? '*';
    let sort = isotopeItem.getAttribute('data-sort') ?? 'original-order';

    let initIsotope;
    imagesLoaded(isotopeItem.querySelector('.isotope-container'), function() {
      initIsotope = new Isotope(isotopeItem.querySelector('.isotope-container'), {
        itemSelector: '.isotope-item',
        layoutMode: layout,
        filter: filter,
        sortBy: sort
      });
    });

    isotopeItem.querySelectorAll('.isotope-filters li').forEach(function(filters) {
      filters.addEventListener('click', function() {
        isotopeItem.querySelector('.isotope-filters .filter-active').classList.remove('filter-active');
        this.classList.add('filter-active');
        initIsotope.arrange({
          filter: this.getAttribute('data-filter')
        });
        if (typeof aosInit === 'function') {
          aosInit();
        }
      }, false);
    });

  });

  /**
   * Initiate Pure Counter
   */
  new PureCounter();

  /**
   * Correct scrolling position upon page load for URLs containing hash links.
   */
  window.addEventListener('load', function(e) {
    if (window.location.hash) {
      if (document.querySelector(window.location.hash)) {
        setTimeout(() => {
          let section = document.querySelector(window.location.hash);
          let scrollMarginTop = getComputedStyle(section).scrollMarginTop;
          window.scrollTo({
            top: section.offsetTop - parseInt(scrollMarginTop),
            behavior: 'smooth'
          });
        }, 100);
      }
    }
  });

  /**
   * Navmenu Scrollspy
   */
  let navmenulinks = document.querySelectorAll('.navmenu a');

  function navmenuScrollspy() {
    navmenulinks.forEach(navmenulink => {
      if (!navmenulink.hash) return;
      let section = document.querySelector(navmenulink.hash);
      if (!section) return;
      let position = window.scrollY + 200;
      if (position >= section.offsetTop && position <= (section.offsetTop + section.offsetHeight)) {
        document.querySelectorAll('.navmenu a.active').forEach(link => link.classList.remove('active'));
        navmenulink.classList.add('active');
      } else {
        navmenulink.classList.remove('active');
      }
    })
  }
  window.addEventListener('load', navmenuScrollspy);
  document.addEventListener('scroll', navmenuScrollspy);

  /**
   * Scroll progress indicator (landing page)
   */
  const scrollProgress = document.querySelector('#scroll-progress');
  function updateScrollProgress() {
    if (!scrollProgress) return;
    const scrollTop = window.scrollY;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
    scrollProgress.style.width = progress + '%';
  }
  if (scrollProgress) {
    document.addEventListener('scroll', updateScrollProgress, { passive: true });
    window.addEventListener('load', updateScrollProgress);
    updateScrollProgress();
  }

  /**
   * Mobile sticky app download bar — appears after scrolling past hero
   */
  const mobileAppBar = document.querySelector('#mobile-app-bar');
  const heroSection = document.querySelector('#hero');
  function toggleMobileAppBar() {
    if (!mobileAppBar || !heroSection) return;
    const pastHero = window.scrollY > heroSection.offsetHeight * 0.6;
    mobileAppBar.classList.toggle('is-visible', pastHero);
    mobileAppBar.setAttribute('aria-hidden', pastHero ? 'false' : 'true');
    document.body.classList.toggle('mobile-app-bar-visible', pastHero);
  }
  if (mobileAppBar && heroSection) {
    document.addEventListener('scroll', toggleMobileAppBar, { passive: true });
    window.addEventListener('load', toggleMobileAppBar);
    toggleMobileAppBar();
  }

  /**
   * Subtle hero parallax on scroll (respects reduced motion)
   */
  const heroBgImage = document.querySelector('.hero-bg-tag');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function updateHeroParallax() {
    if (!heroBgImage || !heroSection || prefersReducedMotion) return;
    if (window.innerWidth < 992) {
      heroBgImage.style.transform = '';
      return;
    }
    const rect = heroSection.getBoundingClientRect();
    if (rect.bottom > 0) {
      const offset = window.scrollY * 0.12;
      heroBgImage.style.transform = 'translateY(calc(-50% + ' + offset + 'px))';
    }
  }
  if (heroBgImage && heroSection && !prefersReducedMotion) {
    document.addEventListener('scroll', updateHeroParallax, { passive: true });
  }

})();


document.querySelectorAll('.faq-question').forEach((question) => {
  question.addEventListener('click', () => {
    const answer = question.nextElementSibling;
    const icon = question.querySelector('i');

    // Toggle the answer display with animation
    answer.classList.toggle('open');
    question.classList.toggle('open');

    // Optional: Close other open answers
    document.querySelectorAll('.faq-answer').forEach((otherAnswer) => {
      if (otherAnswer !== answer) {
        otherAnswer.classList.remove('open');
      }
    });
    document.querySelectorAll('.faq-question').forEach((otherQuestion) => {
      if (otherQuestion !== question) {
        otherQuestion.classList.remove('open');
      }
    });
  });
});
