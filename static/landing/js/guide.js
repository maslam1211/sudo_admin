/* =====================================================================
   SudoTag — How it works ("field guide"). Page-only behaviour; the
   shared header, theme, reveal and dock come from signal.js.
   ===================================================================== */
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function $(s, c) { return (c || document).querySelector(s); }
  function $$(s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function onVisible(el, inFn, outFn, margin) {
    if (!el) return;
    if (!('IntersectionObserver' in window)) { inFn(); return; }
    new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) inFn(); else if (outFn) outFn(); });
    }, { rootMargin: margin || '0px' }).observe(el);
  }

  /* ---------- Hero scope: clock + marks light up as the playhead passes ---------- */
  (function scope() {
    var sc = $('#gScope'); if (!sc) return;
    var head = $('.g-scope__head', sc), screen = $('.g-scope__screen', sc), clock = $('[data-scope-clock]', sc);
    var marks = $$('.g-scope__marks li', sc), t0 = Date.now(), raf = 0, on = false;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function frame() {
      if (!on) return;
      var s = Math.floor((Date.now() - t0) / 1000);
      if (clock) clock.textContent = 'T+' + pad(Math.floor(s / 60)) + ':' + pad(s % 60);
      if (head && screen) {
        var r = screen.getBoundingClientRect(), x = (head.getBoundingClientRect().left - r.left) / (r.width || 1);
        var vis = parseFloat(getComputedStyle(head).opacity) > .2;
        marks.forEach(function (li) {
          var mx = parseFloat(li.style.getPropertyValue('--x')) / 100;
          li.classList.toggle('is-hit', vis && Math.abs(x - mx) < .05);
        });
      }
      raf = requestAnimationFrame(frame);
    }
    onVisible(sc, function () { if (!on) { on = true; raf = requestAnimationFrame(frame); } },
      function () { on = false; cancelAnimationFrame(raf); });
  })();

  /* ---------- Circuit: rail fills with scroll, nodes light as you pass ---------- */
  (function circuit() {
    var c = $('#gCircuit'); if (!c) return;
    var nodes = $$('.g-node', c), ticking = false;
    function update() {
      ticking = false;
      var r = c.getBoundingClientRect(), vh = window.innerHeight, line = vh * .62;
      c.style.setProperty('--fill', clamp((line - r.top) / (r.height || 1), 0, 1).toFixed(4));
      nodes.forEach(function (n) {
        var d = $('.g-node__dot', n).getBoundingClientRect();
        if (d.top + d.height / 2 < line) n.classList.add('is-lit');
        else if (d.top > vh) n.classList.remove('is-lit');
      });
    }
    if (reduce) { nodes.forEach(function (n) { n.classList.add('is-lit'); }); c.style.setProperty('--fill', 1); return; }
    window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    window.addEventListener('resize', update);
    update();
  })();

  /* ---------- Step 04: Live Status cycles, Lost Mode flicks on and off ---------- */
  (function status() {
    var box = $('#gStatus'); if (!box) return;
    var btns = $$('button', box), sw = $('[data-sw]', box.parentNode), i = 0, timer = 0;
    var COL = { safe: 'var(--safe)', amber: 'var(--amber)', signal: 'var(--signal)', alert: 'var(--alert)' };
    function set(n) {
      i = n % btns.length;
      box.style.setProperty('--i', i);
      box.style.setProperty('--pill', COL[btns[i].getAttribute('data-st')]);
      btns.forEach(function (b, k) { b.classList.toggle('is-on', k === i); });
      if (sw) sw.classList.toggle('is-on', i === 3);
    }
    set(0);
    if (reduce) return;
    onVisible(box, function () { clearInterval(timer); timer = setInterval(function () { set(i + 1); }, 1700); },
      function () { clearInterval(timer); });
  })();

  /* ---------- Activation simulator ---------- */
  (function sim() {
    var s = $('#gSim'); if (!s) return;
    var mode = 'app', step = 0, timer = 0, visible = false, pinUntil = 0, DUR = 3600;
    var tabs = $$('[data-sim-mode]', s), screens = $$('.g-scr', s), body = $('.g-phone__body', s);
    function lists() { return $$('.g-sim__steps[data-sim-for="' + mode + '"] button', s); }
    function render() {
      s.setAttribute('data-mode', mode); s.setAttribute('data-step', step);
      if (body) body.style.setProperty('--s', step);
      $$('[data-sim-for]', s).forEach(function (el) { el.hidden = el.getAttribute('data-sim-for') !== mode; });
      tabs.forEach(function (t) { t.setAttribute('aria-selected', t.getAttribute('data-sim-mode') === mode ? 'true' : 'false'); });
      lists().forEach(function (b, k) {
        b.classList.toggle('is-on', k === step); b.classList.toggle('is-done', k < step);
        b.setAttribute('aria-current', k === step ? 'step' : 'false');
        if (k === step && !reduce) { b.classList.remove('is-on'); void b.offsetWidth; b.classList.add('is-on'); }
      });
      screens.forEach(function (sc) { sc.classList.toggle('is-on', sc.getAttribute('data-scr') === mode + '-' + step); });
    }
    function schedule() {
      clearTimeout(timer); s.classList.remove('is-auto');
      if (reduce || !visible) return;
      var wait = Math.max(DUR, pinUntil - Date.now());
      s.style.setProperty('--sim-t', wait + 'ms');
      void s.offsetWidth; s.classList.add('is-auto');
      timer = setTimeout(function () {
        if (step >= 4) { step = 0; mode = mode === 'app' ? 'web' : 'app'; } else step++;
        render(); schedule();
      }, wait);
    }
    tabs.forEach(function (t) {
      t.addEventListener('click', function () { mode = t.getAttribute('data-sim-mode'); step = 0; pinUntil = Date.now() + 8000; render(); schedule(); });
    });
    s.addEventListener('click', function (e) {
      var b = e.target.closest('[data-sim-go]'); if (!b) return;
      step = +b.getAttribute('data-sim-go'); pinUntil = Date.now() + 8000; render(); schedule();
    });
    onVisible(s, function () { if (!visible) { visible = true; schedule(); } }, function () { visible = false; clearTimeout(timer); s.classList.remove('is-auto'); });
    render();
  })();

  /* ---------- The rule: a phone number collapses to 0 ---------- */
  (function zero() {
    var el = $('[data-zero]'); if (!el) return;
    if (reduce) { el.textContent = '0'; return; }
    var G = '#%&$@!?*01', done = false;
    onVisible(el, function () {
      if (done) return; done = true;
      var from = el.textContent, start = null, dur = 1400;
      function step(t) {
        if (start === null) start = t;
        var p = clamp((t - start) / dur, 0, 1), keep = Math.round(from.length * (1 - p)), out = '';
        for (var i = 0; i < keep; i++) out += from[i] === ' ' ? ' ' : G[(Math.random() * G.length) | 0];
        el.textContent = p >= 1 ? '0' : (out || '0');
        if (p < 1) requestAnimationFrame(step);
      }
      setTimeout(function () { requestAnimationFrame(step); }, 350);
    }, null, '0px 0px -20% 0px');
  })();
})();
