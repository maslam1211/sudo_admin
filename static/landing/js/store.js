/* SudoTag Store (/buy) — page polish on top of buy.js. Only touches
   presentation: gallery thumbs, pack shortcuts, stepper, plate input. */
(function () {
  'use strict';
  function $(s, c) { return (c || document).querySelector(s); }
  function $$(s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); }
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Gallery thumbs swap the main image and the zoom source */
  var main = $('#product-main-img'), trigger = $('#product-zoom-trigger');
  $$('.sx-thumb').forEach(function (t, i) {
    t.addEventListener('click', function () {
      $$('.sx-thumb').forEach(function (o) { o.classList.toggle('is-on', o === t); });
      if (!main || !trigger) return;
      trigger.setAttribute('data-full-src', t.getAttribute('data-full'));
      trigger.setAttribute('data-alt', i === 0 ? '0' : '1');
      main.classList.add('is-swap');
      setTimeout(function () { main.src = t.getAttribute('data-src'); main.classList.remove('is-swap'); }, reduce ? 0 : 220);
    });
  });

  /* Pack shortcuts drive the real quantity input (buy.js recalculates) */
  var qty = $('#quantity'), packs = $$('.sx-packs [data-pack]');
  function syncPacks() {
    var v = parseInt(qty && qty.value, 10) || 1;
    packs.forEach(function (b) { b.classList.toggle('is-on', +b.getAttribute('data-pack') === v); });
  }
  function bump() { if (!qty || reduce) return; qty.classList.remove('is-bump'); void qty.offsetWidth; qty.classList.add('is-bump'); }
  packs.forEach(function (b) {
    b.addEventListener('click', function () {
      if (!qty) return;
      qty.value = b.getAttribute('data-pack');
      qty.dispatchEvent(new Event('input', { bubbles: true }));
      syncPacks(); bump();
    });
  });
  if (qty) {
    qty.addEventListener('input', syncPacks);
    $$('.qty-btn').forEach(function (b) { b.addEventListener('click', function () { setTimeout(function () { syncPacks(); bump(); }, 0); }); });
    syncPacks();
  }

  /* Total ticks when it changes */
  var total = $('#summary-total'), wrap = $('#summary-total-wrap');
  if (total && wrap && 'MutationObserver' in window && !reduce) {
    new MutationObserver(function () { wrap.classList.remove('is-tick'); void wrap.offsetWidth; wrap.classList.add('is-tick'); })
      .observe(total, { childList: true, characterData: true, subtree: true });
  }

  /* Stepper: 1 tag → 2 delivery (checkout in view) → 3 pay (required fields filled) */
  var steps = $$('#sxSteps li'), form = $('#checkout-form');
  function setStep(n) {
    steps.forEach(function (s, i) { s.classList.toggle('is-on', i === n); s.classList.toggle('is-done', i < n); });
  }
  if (steps.length && form) {
    var reached = 0;
    function evaluate() {
      var req = $$('[required]', form).filter(function (el) { return el.id !== 'quantity'; });
      var filled = req.length && req.every(function (el) { return String(el.value || '').trim(); });
      var r = $('#checkout').getBoundingClientRect();
      var inView = r.top < window.innerHeight * .75;
      setStep(filled ? 2 : (inView || reached ? 1 : 0));
      if (inView) reached = 1;
    }
    form.addEventListener('input', evaluate);
    window.addEventListener('scroll', evaluate, { passive: true });
    evaluate();
  }

  /* Single coupon field lives in the summary; the hero link jumps to it */
  var jump = $('#sxCouponJump'), couponIn = $('#couponCodeSummary');
  if (jump && couponIn) {
    jump.addEventListener('click', function (e) {
      e.preventDefault();
      var box = couponIn.closest('.coupon-box');
      couponIn.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
      setTimeout(function () {
        couponIn.focus({ preventScroll: true });
        if (box && !reduce) { box.classList.remove('is-flash'); void box.offsetWidth; box.classList.add('is-flash'); }
      }, reduce ? 0 : 450);
    });
  }

  /* Plate-style vehicle number: uppercase alnum + snap */
  var plate = $('#vehicleNumber'), plateField = $('#sxPlateField');
  if (plate) {
    plate.addEventListener('input', function () {
      var v = plate.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12);
      if (v !== plate.value) plate.value = v;
      if (plateField && !reduce) { plateField.classList.remove('is-snap'); void plateField.offsetWidth; plateField.classList.add('is-snap'); }
    });
  }
})();
