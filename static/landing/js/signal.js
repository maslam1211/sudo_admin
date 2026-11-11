/* =====================================================================
   SudoTag — "SIGNAL" landing engine (vanilla, no framework).
   Every effect is skipped or simplified under prefers-reduced-motion,
   Save-Data, or when its section is off-screen.
   ===================================================================== */
(function () {
  'use strict';
  window.__stBooted = true;

  var root = document.documentElement;
  var body = document.body;
  var mqReduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  var reduce = mqReduce.matches;
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  var saveData = !!(navigator.connection && navigator.connection.saveData);
  var lowPower = saveData || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2);
  var DPR = Math.min(window.devicePixelRatio || 1, 1.75);

  function $(s, c) { return (c || document).querySelector(s); }
  function $$(s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function easeInOut(t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function cssVar(n) { return getComputedStyle(root).getPropertyValue(n).trim(); }
  function store(get, k, v) { try { return get ? window.localStorage.getItem(k) : window.localStorage.setItem(k, v); } catch (e) { return null; } }

  /* Run a callback while an element is on screen; returns nothing. */
  function whenVisible(el, onIn, onOut, margin) {
    if (!el) return;
    if (!('IntersectionObserver' in window)) { onIn(); return; }
    new IntersectionObserver(function (es) {
      es.forEach(function (e) { e.isIntersecting ? onIn() : onOut && onOut(); });
    }, { rootMargin: margin || '0px' }).observe(el);
  }

  /* A rAF loop that only runs while visible and the tab is shown. */
  function loop(el, frame) {
    var on = false, raf = 0, vis = false;
    function tick(t) { if (!on) return; frame(t); raf = requestAnimationFrame(tick); }
    function sync() {
      var want = vis && !document.hidden;
      if (want && !on) { on = true; raf = requestAnimationFrame(tick); }
      else if (!want && on) { on = false; cancelAnimationFrame(raf); }
    }
    whenVisible(el, function () { vis = true; sync(); }, function () { vis = false; sync(); }, '100px');
    document.addEventListener('visibilitychange', sync);
  }

  /* ---------- Glyph scramble ---------- */
  var GLYPHS = '!<>-_\\/[]{}=+*^?#%&$01ABCDEFXZ';
  function scramble(el, to, dur, done) {
    var from = el.textContent, len = Math.max(from.length, to.length), start = null;
    var q = [];
    for (var i = 0; i < len; i++) {
      var s = Math.random() * .4 * dur, e = s + (.3 + Math.random() * .3) * dur;
      q.push({ from: from[i] || '', to: to[i] || '', s: s, e: e });
    }
    function step(t) {
      if (start === null) start = t;
      var el2 = t - start, out = '', complete = 0;
      for (var j = 0; j < q.length; j++) {
        var it = q[j];
        if (el2 >= it.e) { complete++; out += it.to; }
        else if (el2 >= it.s) out += it.to === ' ' ? ' ' : GLYPHS[(Math.random() * GLYPHS.length) | 0];
        else out += it.from;
      }
      el.textContent = out;
      if (complete < q.length) requestAnimationFrame(step); else if (done) done();
    }
    if (reduce) { el.textContent = to; if (done) done(); return; }
    requestAnimationFrame(step);
  }

  /* =================================================================
     Theme
     ================================================================= */
  var themeBtn = $('#stTheme');
  var themeListeners = [];
  function applyThemeLabel() {
    if (!themeBtn) return;
    var light = root.getAttribute('data-theme') === 'light';
    themeBtn.setAttribute('aria-label', light ? 'Switch to dark mode' : 'Switch to light mode');
    var meta = $('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', light ? '#F5F3EF' : '#07080B');
  }
  applyThemeLabel();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    store(false, 'st-theme', next);
    applyThemeLabel();
    themeListeners.forEach(function (f) { f(); });
  });

  /* Splash is driven by an inline script in index.html (so it animates before
     this deferred file arrives). Here we only make sure the page is revealed. */
  function ready() { root.classList.add('st-ready'); }
  if (!$('#stIntro') || root.classList.contains('st-intro-skip')) ready();

  /* =================================================================
     Header, progress, dock, menu, scroll spy
     ================================================================= */
  var header = $('#stHeader'), progress = $('#stProgress'), dock = $('#stDock'), hero = $('#hero') || $('main > section');
  var lastY = 0, ticking = false;
  function onScroll() {
    var y = window.scrollY;
    if (header) {
      header.classList.toggle('is-scrolled', y > 24);
      header.classList.toggle('is-hidden', y > 600 && y > lastY + 4 && !body.classList.contains('st-nav-open'));
      if (y < lastY - 4) header.classList.remove('is-hidden');
    }
    if (progress) {
      var max = root.scrollHeight - window.innerHeight;
      progress.style.transform = 'scaleX(' + (max > 0 ? clamp(y / max, 0, 1) : 0) + ')';
    }
    if (dock && hero) dock.classList.toggle('is-visible', y > hero.offsetHeight * .6);
    lastY = y; ticking = false;
  }
  window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();

  var burger = $('#stBurger'), nav = $('#stNav');
  function setMenu(open) {
    body.classList.toggle('st-nav-open', open);
    if (burger) { burger.setAttribute('aria-expanded', String(open)); burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu'); }
  }
  if (burger) burger.addEventListener('click', function () { setMenu(!body.classList.contains('st-nav-open')); });
  if (nav) nav.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setMenu(false); });

  var navLinks = nav ? $$('a[href^="#"]', nav) : [];
  if ('IntersectionObserver' in window && navLinks.length) {
    var spy = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        navLinks.forEach(function (a) { a.classList.toggle('is-active', a.getAttribute('href') === '#' + e.target.id); });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    navLinks.forEach(function (a) { var t = $(a.getAttribute('href')); if (t) spy.observe(t); });
  }

  /* =================================================================
     Reveal + scramble-on-reveal
     ================================================================= */
  var reveals = $$('.st-reveal');
  if (reduce || !('IntersectionObserver' in window)) reveals.forEach(function (el) { el.classList.add('is-in'); });
  else {
    var rio = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('is-in'); rio.unobserve(e.target); } });
    }, { rootMargin: '0px 0px -8% 0px', threshold: .08 });
    reveals.forEach(function (el) { rio.observe(el); });
  }

  $$('[data-scramble]').forEach(function (el) {
    var final = el.textContent;
    whenVisible(el, function () { if (!el.dataset.done) { el.dataset.done = '1'; scramble(el, final, 1100); } });
  });
  /* Masked readouts: a real-looking number scrambles to glyphs and back to a mask. */
  $$('[data-scramble-loop]').forEach(function (el) {
    if (reduce) return;
    var a = el.textContent, alt = el.getAttribute('data-alt'), masks = [alt || a.replace(/[0-9]/g, '•'), a], k = 0, timer = 0;
    whenVisible(el, function () {
      if (timer) return;
      timer = setInterval(function () { scramble(el, masks[k++ % 2], 900); }, 2800);
    }, function () { clearInterval(timer); timer = 0; });
  });

  /* =================================================================
     Micro-interactions: magnetic buttons, tilt, spotlight
     ================================================================= */
  if (finePointer && !reduce) {
    $$('[data-magnetic]').forEach(function (b) {
      b.addEventListener('pointermove', function (e) {
        var r = b.getBoundingClientRect();
        b.style.setProperty('--mx', ((e.clientX - r.left - r.width / 2) * .22).toFixed(1) + 'px');
        b.style.setProperty('--my', ((e.clientY - r.top - r.height / 2) * .32).toFixed(1) + 'px');
      });
      b.addEventListener('pointerleave', function () { b.style.setProperty('--mx', '0px'); b.style.setProperty('--my', '0px'); });
    });
    $$('[data-tilt]').forEach(function (t) {
      t.addEventListener('pointermove', function (e) {
        var r = t.getBoundingClientRect(), px = (e.clientX - r.left) / r.width - .5, py = (e.clientY - r.top) / r.height - .5;
        t.style.setProperty('--ry', (px * 12).toFixed(2) + 'deg');
        t.style.setProperty('--rx', (-py * 12).toFixed(2) + 'deg');
        t.style.setProperty('--gx', (px * 50).toFixed(1) + '%');
      });
      t.addEventListener('pointerleave', function () { t.style.setProperty('--rx', '0deg'); t.style.setProperty('--ry', '0deg'); t.style.setProperty('--gx', '0%'); });
    });
    document.addEventListener('pointermove', function (e) {
      var g = e.target.closest && e.target.closest('.st-glass');
      if (!g) return;
      var r = g.getBoundingClientRect();
      g.style.setProperty('--sx', (e.clientX - r.left) + 'px');
      g.style.setProperty('--sy', (e.clientY - r.top) + 'px');
    }, { passive: true });
  }

  /* =================================================================
     Hero: vehicle morph + persona switcher
     ================================================================= */
  var PERSONAS = {
    car: 'Blocking a gate? They scan. You move. Nobody swaps numbers.',
    bike: 'Lights left on? A stranger tells you before the battery dies.',
    scooter: 'Lost in a sea of scooters? The community pings you.',
    auto: 'Passenger forgot a bag? They reach you, not your number.',
    taxi: 'Guest needs the driver? Masked call, ride after ride.',
    truck: 'Blocking a dock at 3 AM? The driver on shift gets the alert.'
  };
  var ORDER = ['car', 'bike', 'scooter', 'auto', 'taxi', 'truck'];
  var morphUses = $$('#stMorph use'), morphLabel = $('#stMorphLabel'), morphStory = $('#stMorphStory');
  var chips = $$('.st-persona__chips button');
  var curPersona = 'car', morphTimer = 0, morphPausedUntil = 0;

  function setPersona(p, fromUser) {
    if (p === curPersona && !fromUser) return;
    morphUses.forEach(function (u) {
      var on = u.getAttribute('data-v') === p, was = u.classList.contains('is-on');
      u.classList.remove('is-out');
      if (was && !on) { u.classList.remove('is-on'); u.classList.add('is-out'); setTimeout(function () { u.classList.remove('is-out'); }, 1100); }
      if (on) u.classList.add('is-on');
    });
    curPersona = p;
    if (hero) hero.setAttribute('data-persona', p);
    if (morphLabel) scramble(morphLabel, p === 'auto' ? 'auto' : p, 500);
    if (morphStory) {
      morphStory.classList.add('is-swap');
      setTimeout(function () { morphStory.textContent = PERSONAS[p]; morphStory.classList.remove('is-swap'); }, 260);
    }
    chips.forEach(function (c) { c.setAttribute('aria-checked', String(c.getAttribute('data-persona') === p)); });
  }
  chips.forEach(function (c) {
    c.addEventListener('click', function () { morphPausedUntil = Date.now() + 9000; setPersona(c.getAttribute('data-persona'), true); });
  });
  /* Live signal loop: each cycle = one vehicle story (scan → alert → reply),
     then the next persona. Replaces the old 2.8s persona timer. */
  var LOOP = {
    car: ['"Blocking the gate"', '"Moving it now 🙏"'],
    bike: ['"Headlight left on"', '"Thanks! Switching it off"'],
    scooter: ['"Your scooter fell over"', '"Coming down 🙏"'],
    auto: ['"Passenger left a bag"', '"On my way back"'],
    taxi: ['"Guest is waiting"', '"2 min away"'],
    truck: ['"Blocking the dock"', '"Shift driver moving it"']
  };
  var loopEl = $('#stLoop'), stage = $('.st-beacon-stage'), loopReason = $('[data-loop-reason]'), loopReply = $('[data-loop-reply]');
  var loopFloats = loopEl ? $$('.st-float', loopEl) : [], loopT = [], loopOn = false;
  function beat(n) {
    if (!loopEl) return;
    loopEl.classList.remove('is-b1', 'is-b2', 'is-b3');
    if (n) loopEl.classList.add('is-b' + n);
    loopFloats.forEach(function (f) { f.classList.toggle('is-cur', +f.getAttribute('data-b') === n); });
    if (stage) stage.classList.toggle('is-scan', n === 1);
  }
  function cycle() {
    loopT.forEach(clearTimeout); loopT = [];
    if (!loopOn) return;
    var m = LOOP[curPersona] || LOOP.car;
    if (loopReason) loopReason.textContent = m[0];
    if (loopReply) loopReply.textContent = m[1];
    beat(0);
    loopT.push(setTimeout(function () { beat(1); }, 500));
    loopT.push(setTimeout(function () { beat(2); }, 1900));
    loopT.push(setTimeout(function () { beat(3); }, 3400));
    loopT.push(setTimeout(function () {
      if (Date.now() >= morphPausedUntil) setPersona(ORDER[(ORDER.indexOf(curPersona) + 1) % ORDER.length]);
      cycle();
    }, 6200));
  }
  if (loopEl && reduce) beat(3);
  else if (loopEl) whenVisible(hero, function () { if (!loopOn) { loopOn = true; cycle(); } }, function () { loopOn = false; loopT.forEach(clearTimeout); });
  chips.forEach(function (c) { c.addEventListener('click', function () { if (loopOn) cycle(); }); });

  /* "private." encrypts and resolves every few seconds */
  var enc = $('[data-encrypt]');
  if (enc && !reduce) {
    var encWord = enc.textContent;
    setInterval(function () {
      if (document.hidden || window.scrollY > window.innerHeight) return;
      var g = ''; for (var k = 0; k < encWord.length; k++) g += GLYPHS[(Math.random() * GLYPHS.length) | 0];
      enc.textContent = g; scramble(enc, encWord, 900);
    }, 7000);
  }

  /* Privacy lens: follows the pointer; drifts on its own when idle / on touch */
  (function lens() {
    var wall = $('#stNumwall'); if (!wall || !hero) return;
    var lensRows = $$('[data-lens] span', wall), src = lensRows.map(function (r) { return r.textContent; });
    var tx = .7, ty = .4, x = .7, y = .4, lastMove = 0, t0 = performance.now(), lastGlyph = 0;
    if (finePointer) hero.addEventListener('pointermove', function (e) {
      var r = wall.getBoundingClientRect(); tx = (e.clientX - r.left) / r.width; ty = (e.clientY - r.top) / r.height; lastMove = performance.now();
    });
    function enc(str) {
      var out = '';
      for (var i = 0; i < str.length; i++) { var ch = str[i]; out += /[0-9]/.test(ch) ? GLYPHS[(Math.random() * GLYPHS.length) | 0] : ch; }
      return out;
    }
    if (reduce) { lensRows.forEach(function (r, i) { r.textContent = src[i].replace(/[0-9]/g, '•'); }); return; }
    loop(hero, function (t) {
      if (t - lastMove > 2200) {                     // idle: a slow figure-eight
        var k = (t - t0) / 1000;
        tx = .6 + Math.sin(k * .45) * .28; ty = .55 + Math.sin(k * .9) * .14;
      }
      x += (tx - x) * .08; y += (ty - y) * .08;
      wall.style.setProperty('--mx', (x * 100).toFixed(2) + '%');
      wall.style.setProperty('--my', (y * 100).toFixed(2) + '%');
      wall.style.setProperty('--px', (x * wall.clientWidth).toFixed(1) + 'px');
      wall.style.setProperty('--py', (y * wall.clientHeight).toFixed(1) + 'px');
      if (t - lastGlyph > 90) { lastGlyph = t; lensRows.forEach(function (r, i) { r.textContent = enc(src[i]); }); }
    });
  })();

  /* =================================================================
     Hero canvas: night road, headlight streaks, wet reflections,
     signal rings from the tag.
     ================================================================= */
  (function heroRoad() {
    var cv = $('#stRoad');
    if (!cv || reduce || lowPower || !cv.getContext) { if (cv) cv.remove(); return; }
    var ctx = cv.getContext('2d'), w = 0, h = 0, vx = 0, hy = 0, lights = [], rings = [], lastRing = 0, beacon = { x: 0, y: 0 };
    var palette = {};
    function readPalette() {
      var light = root.getAttribute('data-theme') === 'light';
      palette = { light: light, grid: light ? 'rgba(20,20,30,.07)' : 'rgba(255,255,255,.05)', signal: cssVar('--signal') || '#FF7A1A' };
    }
    readPalette(); themeListeners.push(readPalette);
    function size() {
      var r = cv.getBoundingClientRect();
      w = r.width; h = r.height; cv.width = w * DPR; cv.height = h * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      vx = w > 960 ? w * .7 : w * .5; hy = h * (w > 960 ? .52 : .6);
      var tag = $('.st-tag3d'); if (tag) { var tr = tag.getBoundingClientRect(); beacon.x = tr.left + tr.width / 2 - r.left; beacon.y = tr.top + tr.height / 2 - r.top; }
    }
    size(); window.addEventListener('resize', size);
    var LANES = [-3.2, -1.6, 1.6, 3.2];
    function spawn() {
      var lane = LANES[(Math.random() * LANES.length) | 0], toward = lane > 0;
      lights.push({ lane: lane + (Math.random() - .5) * .3, z: toward ? 18 : 1.1, v: (toward ? -1 : 1) * (.05 + Math.random() * .05), toward: toward, prev: null });
    }
    function project(lane, z) { var s = 1 / z; return { x: vx + lane * s * w * .09, y: hy + s * (h - hy) * .9, s: s }; }
    var t0 = 0;
    loop(cv, function (t) {
      var dt = Math.min(48, t - (t0 || t)); t0 = t;
      ctx.clearRect(0, 0, w, h);
      // perspective ground grid
      ctx.strokeStyle = palette.grid; ctx.lineWidth = 1; ctx.beginPath();
      for (var i = -10; i <= 10; i++) { var p = project(i * .9, 1); ctx.moveTo(vx, hy); ctx.lineTo(p.x, h + 40); }
      var off = (t * .0004) % 1;
      for (var k = 0; k < 12; k++) { var z = 1 + Math.pow((k + 1 - off), 1.6) * .6; var yy = project(0, z).y; ctx.moveTo(0, yy); ctx.lineTo(w, yy); }
      ctx.stroke();
      // headlight / taillight streaks
      if (Math.random() < .06 && lights.length < 26) spawn();
      ctx.globalCompositeOperation = palette.light ? 'source-over' : 'lighter';
      for (var j = lights.length - 1; j >= 0; j--) {
        var L = lights[j];
        L.z += L.v * dt * .06 * L.z;
        var P = project(L.lane, L.z);
        if (L.z < .9 || L.z > 20) { lights.splice(j, 1); continue; }
        if (L.prev) {
          var col = L.toward ? (palette.light ? 'rgba(61,123,255,' : 'rgba(255,240,215,') : (palette.light ? 'rgba(238,106,12,' : 'rgba(255,77,94,');
          var a = clamp(P.s * 1.4, .05, .9);
          var g = ctx.createLinearGradient(L.prev.x, L.prev.y, P.x, P.y);
          g.addColorStop(0, col + '0)'); g.addColorStop(1, col + a + ')');
          ctx.strokeStyle = g; ctx.lineWidth = Math.max(1, P.s * 3.2); ctx.lineCap = 'round';
          ctx.beginPath(); ctx.moveTo(L.prev.x, L.prev.y); ctx.lineTo(P.x, P.y); ctx.stroke();
          // wet-road reflection
          ctx.strokeStyle = col + (a * .18) + ')'; ctx.lineWidth = Math.max(1, P.s * 2);
          ctx.beginPath(); ctx.moveTo(P.x, P.y + 2); ctx.lineTo(P.x, P.y + 10 + P.s * 60); ctx.stroke();
        }
        if (!L.prev || Math.random() < .5) L.prev = { x: lerp(L.prev ? L.prev.x : P.x, P.x, .25), y: lerp(L.prev ? L.prev.y : P.y, P.y, .25) };
        if (Math.abs(L.prev.x - P.x) + Math.abs(L.prev.y - P.y) > 140 * P.s + 20) L.prev = { x: lerp(L.prev.x, P.x, .5), y: lerp(L.prev.y, P.y, .5) };
      }
      ctx.globalCompositeOperation = 'source-over';
      // signal rings from the tag
      if (t - lastRing > 1700) { rings.push({ r: 40, a: .55 }); lastRing = t; }
      ctx.strokeStyle = palette.signal;
      for (var q = rings.length - 1; q >= 0; q--) {
        var R = rings[q]; R.r += dt * .16; R.a -= dt * .00042;
        if (R.a <= 0) { rings.splice(q, 1); continue; }
        ctx.globalAlpha = R.a; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(beacon.x, beacon.y, R.r, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    });
  })();

  /* =================================================================
     Privacy moment: +91 number → particles → SudoTag wordmark
     ================================================================= */
  (function dissolve() {
    var sec = $('#privacy'), cv = $('#stDissolve');
    if (!sec || !cv) return;
    var caps = $$('.st-cap', sec);
    if (reduce || lowPower || !cv.getContext) { sec.classList.add('is-static'); return; }
    var ctx = cv.getContext('2d'), w = 0, h = 0, parts = [], built = false, prog = 0, colors = {};
    function readColors() { colors = { hi: cssVar('--text-hi') || '#fff', lo: cssVar('--text-lo') || '#888', sig: cssVar('--signal') || '#FF7A1A' }; }
    readColors(); themeListeners.push(readColors);

    function sample(draw, gap) {
      var oc = document.createElement('canvas'); oc.width = w; oc.height = h;
      var o = oc.getContext('2d'); draw(o);
      var d = o.getImageData(0, 0, w, h).data, pts = [];
      for (var y = 0; y < h; y += gap) for (var x = 0; x < w; x += gap) {
        var i = (y * w + x) * 4;
        if (d[i + 3] > 128) pts.push({ x: x, y: y, dot: d[i] > 200 && d[i + 1] < 80 });
      }
      return pts;
    }
    function build() {
      var r = cv.getBoundingClientRect(); w = Math.round(r.width); h = Math.round(r.height);
      if (!w || !h) return;
      cv.width = w * DPR; cv.height = h * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      var gap = w < 700 ? 4 : 5, cy = h * .42;
      var A = sample(function (o) {
        var fs = Math.min(w * (w < 700 ? .1 : .085), 96);
        o.font = '700 ' + fs + 'px "JetBrains Mono", monospace'; o.textAlign = 'center'; o.textBaseline = 'middle';
        o.fillStyle = '#fff'; o.fillText('+91 98470 •••••', w / 2, cy);
      }, gap);
      var B = sample(function (o) {
        var fs = Math.min(w * (w < 700 ? .2 : .16), 190);
        o.font = '700 ' + fs + 'px "Space Grotesk", sans-serif'; o.textAlign = 'center'; o.textBaseline = 'middle';
        var tw = o.measureText('SudoTag').width, dot = fs * .16;
        o.fillStyle = '#fff'; o.fillText('SudoTag', w / 2 - dot, cy);
        o.fillStyle = '#f00'; o.beginPath(); o.arc(w / 2 + tw / 2 + dot * .2, cy + fs * .28, dot, 0, Math.PI * 2); o.fill();
      }, gap);
      if (!A.length || !B.length) return;
      var n = Math.max(A.length, B.length);
      parts = [];
      for (var i = 0; i < n; i++) {
        var a = A[i % A.length], b = B[(i * 7919) % B.length], ang = Math.random() * Math.PI * 2, rad = (.25 + Math.random() * .6) * Math.max(w, h) * .5;
        parts.push({ ax: a.x, ay: a.y, bx: b.x, by: b.y, dot: b.dot, sx: w / 2 + Math.cos(ang) * rad, sy: cy + Math.sin(ang) * rad * .6, d: Math.random() * .35, ph: Math.random() * 6.28 });
      }
      built = true;
    }
    function measure() {
      var r = sec.getBoundingClientRect(), total = sec.offsetHeight - window.innerHeight;
      prog = clamp(-r.top / (total || 1), 0, 1);
      var c = prog < .3 ? 0 : prog < .68 ? 1 : 2;
      caps.forEach(function (el) { el.classList.toggle('is-on', +el.getAttribute('data-cap') === c); });
    }
    (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(function () { build(); });
    var rz = 0; window.addEventListener('resize', function () { clearTimeout(rz); rz = setTimeout(build, 200); });
    window.addEventListener('scroll', measure, { passive: true }); measure();

    loop(sec, function (t) {
      if (!built) return;
      ctx.clearRect(0, 0, w, h);
      var s = 1.6;
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i], x, y, col = colors.lo, k;
        var p1 = clamp((prog - .12 - p.d * .3) / .3, 0, 1);   // number → scatter
        var p2 = clamp((prog - .45 - p.d * .3) / .3, 0, 1);   // scatter → logo
        if (p2 > 0) { k = easeInOut(p2); x = lerp(p.sx, p.bx, k); y = lerp(p.sy, p.by, k); col = p.dot ? colors.sig : (k > .9 ? colors.hi : colors.sig); }
        else { k = easeOut(p1); x = lerp(p.ax, p.sx, k); y = lerp(p.ay, p.sy, k); col = k > .05 ? colors.sig : colors.lo; }
        var jit = (p1 > 0 && p2 < 1) ? Math.sin(t * .002 + p.ph) * 3 : Math.sin(t * .0012 + p.ph) * .4;
        ctx.globalAlpha = p2 > 0 ? .5 + p2 * .5 : 1 - p1 * .4;
        ctx.fillStyle = col; ctx.fillRect(x + jit, y + jit * .6, s, s);
      }
      ctx.globalAlpha = 1;
    });
  })();

  /* =================================================================
     How it works: 5-chapter story (scroll-driven on desktop,
     6s autoplay + tap on mobile)
     ================================================================= */
  (function story() {
    var st = $('#stStory'); if (!st) return;
    var rail = $$('.st-rail button', st), arts = $$('.st-story__text article', st), stage = $('.st-story__stage', st);
    var glyph = $('[data-glyph]', st), cur = -1, timer = 0, visible = false;
    var hudCh = $('[data-hud-ch]', st), hudLabel = $('[data-hud-label]', st), hudLink = $('[data-hud-link]', st), num = $('[data-story-num]', st);
    var HUD = [['TAG ARMED', 'IDLE', ''], ['SCAN DETECTED', 'HANDSHAKE', 'var(--amber)'], ['RELAY · MASKING', 'ENCRYPTED', 'var(--signal-2)'], ['OWNER PINGED', 'DELIVERED', 'var(--safe)'], ['CHANNEL OPEN', 'LIVE', 'var(--safe)']];
    var desktop = window.matchMedia('(min-width: 1024px)');
    function scrollMode() { return desktop.matches && !reduce; }
    var PHASE = [0, 0, 1, 2, 2], PWORD = ['SCAN', 'SIGNAL', 'RESPOND'], SPAN = [[0, 2], [2, 3], [3, 5]];
    var phases = $$('.st-phase li', st), pword = $('[data-phase-word]', st), sweep = $('.st-sweep', st);
    /* fill each phase segment by story progress (x chapters out of 5) */
    function phaseFill(x) {
      phases.forEach(function (li, i) {
        var a = SPAN[i][0], b = SPAN[i][1];
        li.style.setProperty('--f', clamp((x - a) / (b - a), 0, 1).toFixed(3));
      });
    }

    function set(n) {
      n = clamp(n, 0, 4); if (n === cur) return; cur = n;
      st.setAttribute('data-chapter', n);
      st.style.setProperty('--p', n / 4);
      $('.st-rail', st).style.setProperty('--p', n / 4);
      rail.forEach(function (b, i) { b.classList.toggle('is-on', i === n); b.classList.toggle('is-done', i < n); b.setAttribute('aria-current', i === n ? 'step' : 'false'); });
      arts.forEach(function (a, i) { a.classList.toggle('is-on', i === n); });
      var lbl = '0' + (n + 1);
      if (hudCh) hudCh.textContent = lbl;
      if (hudLabel) { if (reduce) hudLabel.textContent = HUD[n][0]; else scramble(hudLabel, HUD[n][0], 500); }
      if (hudLink) hudLink.textContent = HUD[n][1];
      if (stage) { if (HUD[n][2]) stage.style.setProperty('--hud-c', HUD[n][2]); else stage.style.removeProperty('--hud-c'); }
      if (num) { num.textContent = lbl; num.classList.remove('is-tick'); void num.offsetWidth; num.classList.add('is-tick'); }
      /* Scan → Signal → Respond phase bar, backdrop word, beam sweep */
      var ph = PHASE[n];
      phases.forEach(function (li, i) { li.classList.toggle('is-on', i === ph); li.classList.toggle('is-done', i < ph); });
      st.setAttribute('data-phase', ph);
      if (pword && pword.textContent !== PWORD[ph]) { if (reduce) pword.textContent = PWORD[ph]; else scramble(pword, PWORD[ph], 700); }
      if (sweep && !reduce) { sweep.classList.remove('is-go'); void sweep.offsetWidth; sweep.classList.add('is-go'); }
      if (!scrollMode()) phaseFill(n + 1, 5);
      if (glyph) {
        if (n === 2) scramble(glyph, '#&%@ MASKED %$#!', 1200);
        else if (n > 2) glyph.textContent = '•••• MASKED ••••';
        else glyph.textContent = '+91 98470 12345';
      }
      if (!scrollMode()) restartAuto();
    }
    function restartAuto() {
      clearTimeout(timer); st.classList.remove('is-autoplay');
      if (reduce || scrollMode() || !visible) return;
      void st.offsetWidth; st.classList.add('is-autoplay');
      timer = setTimeout(function () { set(cur >= 4 ? 0 : cur + 1); }, 6000);
    }
    function onScroll() {
      if (!scrollMode()) return;
      var r = st.getBoundingClientRect(), total = st.offsetHeight - window.innerHeight;
      var prog = clamp(-r.top / (total || 1), 0, .999);
      set(Math.floor(prog * 5));
      phaseFill(prog * 5);
      st.style.setProperty('--sp', prog.toFixed(3));
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    rail.forEach(function (b, i) {
      b.addEventListener('click', function () {
        if (scrollMode()) {
          var total = st.offsetHeight - window.innerHeight;
          window.scrollTo({ top: st.getBoundingClientRect().top + window.scrollY + total * (i + .5) / 5, behavior: 'smooth' });
        } else set(i);
      });
    });
    $$('[data-step]', st).forEach(function (b) { b.addEventListener('click', function () { set(cur + (+b.getAttribute('data-step'))); }); });
    if (stage) stage.addEventListener('click', function () { if (!scrollMode()) set(cur >= 4 ? 0 : cur + 1); });
    whenVisible(st, function () { visible = true; restartAuto(); }, function () { visible = false; clearTimeout(timer); st.classList.remove('is-autoplay'); });
    set(0); onScroll();
  })();

  /* =================================================================
     Scan console: tab links, plate "snap"
     ================================================================= */
  /* Coming from another page via a Scan / Plate link: open the right tab */
  (function () {
    var want = null; try { want = sessionStorage.getItem('st-scan-tab'); sessionStorage.removeItem('st-scan-tab'); } catch (e) {}
    var t = want && $('.find-vehicle-tab[data-tab="' + want + '"]');
    if (t && !t.classList.contains('is-active')) setTimeout(function () { t.click(); }, 300);
  })();
  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-scan-tab]'); if (!link) return;
    if (!$('#findVehicleCard')) { try { sessionStorage.setItem('st-scan-tab', link.getAttribute('data-scan-tab')); } catch (err) {} return; }
    var tab = $('.find-vehicle-tab[data-tab="' + link.getAttribute('data-scan-tab') + '"]');
    if (tab && !tab.classList.contains('is-active')) tab.click();
    var card = $('#findVehicleCard'); if (card) card.setAttribute('data-mode', link.getAttribute('data-scan-tab'));
  });
  var plateField = $('#stPlateField'), plateInput = $('#findVehiclePlateInput');
  if (plateField && plateInput && !reduce) {
    plateInput.addEventListener('input', function () {
      plateField.classList.remove('is-snap'); void plateField.offsetWidth; plateField.classList.add('is-snap');
    });
  }
  var fvCard = $('#findVehicleCard');
  if (fvCard) $$('.find-vehicle-tab', fvCard).forEach(function (t) {
    t.addEventListener('click', function () { fvCard.setAttribute('data-mode', t.getAttribute('data-tab')); });
  });

  /* One scanner, two jobs: the console window shows where a scan goes.
     QR mode alternates New -> Activate / Active -> Notify; plate mode routes
     to Owner found and mirrors what the visitor types onto the plate. */
  (function routes() {
    var win = fvCard && $('.st-route', fvCard); if (!win) return;
    var read = $('[data-route-readout]', win), plateEl = $('[data-route-plate]', win);
    var picks = $$('[data-route-pick]'), cur = '', timer = 0, pinUntil = 0, visible = false, hitTimer = 0, camLabel = $('[data-cam-label]', win);
    var TXT = { 'new': 'TAG #A7F3 · UNCLAIMED → ACTIVATE', active: 'TAG #K2Q9 · LIVE → NOTIFY OWNER', plate: 'OCR · PLATE READ → OWNER MATCH' };
    function show(r, auto) {
      picks.forEach(function (b) {
        var on = b.getAttribute('data-route-pick') === r;
        b.classList.toggle('is-on', on); b.classList.remove('is-auto');
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        if (on && auto && !reduce) { void b.offsetWidth; b.classList.add('is-auto'); }
      });
      if (r === cur) return; cur = r;
      win.setAttribute('data-route', r);
      /* scan → detect → result: the box hunts, then snaps and the card slides in */
      clearTimeout(hitTimer); win.classList.remove('is-hit');
      if (camLabel) camLabel.textContent = r === 'plate' ? 'Reading plate' : 'Scanning';
      if (read) read.textContent = r === 'plate' ? 'OCR · READING…' : 'SIGNAL · SEARCHING…';
      hitTimer = setTimeout(function () {
        win.classList.add('is-hit');
        if (camLabel) camLabel.textContent = r === 'plate' ? 'Plate read' : r === 'new' ? 'New tag' : 'Live tag';
        if (read) { if (reduce) read.textContent = TXT[r]; else scramble(read, TXT[r], 650); }
      }, reduce ? 0 : 900);
    }
    function isPlate() { return fvCard.getAttribute('data-mode') === 'plate'; }
    function tick() {
      clearTimeout(timer);
      if (!visible || reduce || isPlate()) return;
      timer = setTimeout(function () {
        if (Date.now() >= pinUntil && !isPlate()) show(cur === 'new' ? 'active' : 'new', true);
        tick();
      }, 4200);
    }
    function sync() { if (isPlate()) show('plate'); else if (cur === 'plate' || !cur) show('new', true); tick(); }
    if ('MutationObserver' in window) new MutationObserver(sync).observe(fvCard, { attributes: true, attributeFilter: ['data-mode'] });
    picks.forEach(function (b) {
      b.addEventListener('click', function () {
        var r = b.getAttribute('data-route-pick'), tab = $('.find-vehicle-tab[data-tab="' + (r === 'plate' ? 'plate' : 'qr') + '"]', fvCard);
        pinUntil = Date.now() + 9000;
        if (tab && !tab.classList.contains('is-active')) tab.click();
        fvCard.setAttribute('data-mode', r === 'plate' ? 'plate' : 'qr');
        show(r); tick();
      });
    });
    var plateIn = $('#findVehiclePlateInput');
    if (plateIn && plateEl) plateIn.addEventListener('input', function () {
      var v = plateIn.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10);
      var m = v.match(/^([A-Z]{0,2})(\d{0,2})([A-Z]{0,3})(\d{0,4})$/);
      plateEl.textContent = v ? (m ? [m[1], m[2], m[3], m[4]].filter(Boolean).join(' ') : v) : 'KL 10 AY 2121';
    });
    whenVisible(win, function () { visible = true; sync(); }, function () { visible = false; clearTimeout(timer); });
    show(isPlate() ? 'plate' : 'new');
  })();

  /* =================================================================
     Signal dock: sliding beacon, context-aware scan orb, tuck on scroll
     ================================================================= */
  (function dockFx() {
    var d = $('#stDock'); if (!d || !d.classList.contains('st-dock--fab')) return;
    var mark = $('.st-dock__mark', d), items = $$('[data-dock]', d), fab = $('.st-dock__fab', d), lbl = $('[data-dock-label]', d);
    var cur = null, inScan = false, lastY = window.scrollY;
    function place(k) {
      cur = k;
      items.forEach(function (a) { a.classList.toggle('is-on', a.getAttribute('data-dock') === k); });
      var it = k && $('[data-dock="' + k + '"]', d);
      if (mark) {
        if (it) { mark.style.setProperty('--x', (it.offsetLeft + it.offsetWidth / 2) + 'px'); mark.classList.add('is-on'); }
        else mark.classList.remove('is-on');
      }
    }
    /* which dock slot matches the section in the middle of the screen */
    var map = [['#scan', 'scan'], ['#help', 'help'], ['#steps', 'steps'], ['#activate', 'activate']], seen = {};
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { seen[e.target.id] = e.isIntersecting; });
        var hit = null;
        map.forEach(function (m) { var id = m[0].slice(1); if (seen[id] && $('[data-dock="' + m[1] + '"]', d)) hit = m[1]; });
        inScan = !!seen.scan;
        d.classList.toggle('is-cam', inScan);
        if (inScan) d.classList.remove('is-tuck');
        if (lbl) lbl.textContent = inScan ? 'Camera' : 'Scan';
        if (fab) fab.setAttribute('aria-label', inScan ? 'Open the camera to scan' : 'Scan a SudoTag QR');
        place(hit);
      }, { rootMargin: '-45% 0px -45% 0px' });
      map.forEach(function (m) { var t = $(m[0]); if (t) io.observe(t); });
    }
    window.addEventListener('resize', function () { place(cur); });
    /* orb: anywhere → jump to the scanner; inside it → open the camera directly */
    if (fab) fab.addEventListener('click', function (e) {
      fab.classList.remove('is-tap'); void fab.offsetWidth; fab.classList.add('is-tap');
      if (navigator.vibrate) { try { navigator.vibrate(8); } catch (err) {} }
      if (!inScan) return;
      var card = $('#findVehicleCard'), btn = $(card && card.getAttribute('data-mode') === 'plate' ? '#findVehiclePlateScanBtn' : '#findVehicleScanBtn');
      if (btn) { e.preventDefault(); e.stopPropagation(); btn.click(); }
    });
    /* tuck away while reading down, return on the way up */
    var ticking = false, idle = 0;
    window.addEventListener('scroll', function () {
      clearTimeout(idle); idle = setTimeout(function () { d.classList.remove('is-tuck'); }, 900);
      if (ticking) return; ticking = true;
      requestAnimationFrame(function () {
        var y = window.scrollY;
        if (y > lastY + 8 && !inScan) d.classList.add('is-tuck');
        else if (y < lastY - 6 || inScan) d.classList.remove('is-tuck');
        lastY = y; ticking = false;
      });
    }, { passive: true });
  })();

  /* =================================================================
     Features: tile → full sheet with phone mock
     ================================================================= */
  var FEATURES = {
    qr: { k: 'Core', t: 'Private QR contact', l: 'The tag is a door that only opens one way. Scanners reach you, and they never see who you are.',
      b: ['Notify, chat, SMS or masked call', 'No app needed for the person scanning', 'Weatherproof, no battery, no charging'],
      s: '<p class="st-ph-title">Contact owner</p><div class="st-ph-card"><i class="bi bi-bell"></i><div>Notify<small>Instant push alert</small></div></div><div class="st-ph-card"><i class="bi bi-chat-dots"></i><div>Chat<small>Private thread</small></div></div><div class="st-ph-card"><i class="bi bi-telephone"></i><div>Masked call<small>Numbers hidden both ways</small></div></div><div class="st-ph-btn">Send alert</div>' },
    garage: { k: 'Garage', t: 'Multi-vehicle garage', l: 'Every vehicle you own or manage, each with its own tag, in one account.',
      b: ['Cars, bikes, scooters, autos and trucks', 'Per-vehicle alert settings', 'Switch vehicles in one tap'],
      s: '<p class="st-ph-title">My garage</p><div class="st-ph-card"><i class="bi bi-car-front"></i><div>KL 11 AB 1234<small>Tag active</small></div></div><div class="st-ph-card"><i class="bi bi-bicycle"></i><div>KL 10 AY 2121<small>Tag active</small></div></div><div class="st-ph-card"><i class="bi bi-scooter"></i><div>KL 07 CD 5678<small>Lost Mode off</small></div></div><div class="st-ph-btn">Add vehicle</div>' },
    locker: { k: 'Coming soon', t: 'Document locker', l: "We're building a secure place in the app for your RC, insurance and PUC. It isn't live yet.",
      b: ['Keep RC, insurance and PUC in one place', 'See expiry dates at a glance', 'Shared only with people you assign'],
      s: '<p class="st-ph-title">Documents</p><div class="st-ph-card" style="opacity:.55"><i class="bi bi-file-earmark-text"></i><div>Registration (RC)<small>Coming soon</small></div></div><div class="st-ph-card" style="opacity:.55"><i class="bi bi-shield-check"></i><div>Insurance<small>Coming soon</small></div></div><div class="st-ph-card" style="opacity:.55"><i class="bi bi-wind"></i><div>PUC<small>Coming soon</small></div></div><div class="st-ph-btn" style="background:#1F2633;color:#8C95A8">Coming soon</div>' },
    assign: { k: 'Coming soon', t: 'Family & temp assign', l: "Coming soon. Someone else driving today? You'll be able to hand the alerts over for exactly as long as you choose.",
      b: ['Assign family members permanently', 'Temporary assign with an end time', 'Alerts return to you automatically'],
      s: '<p class="st-ph-title">Assign vehicle</p><div class="st-ph-card"><i class="bi bi-person"></i><div>Amma<small>Family · always</small></div></div><div class="st-ph-card"><i class="bi bi-clock-history"></i><div>Driver (Ravi)<small>Until 8:00 PM</small></div></div><div class="st-ph-btn">Assign</div>' },
    lost: { k: 'Coming soon', t: 'Lost Mode + community tips', l: "Coming soon. Mark a vehicle lost and every scan becomes a lead, with location and time.",
      b: ['One tap to turn on or off', 'Tips arrive with location', 'Finders stay anonymous too'],
      s: '<p class="st-ph-title">Lost Mode · ON</p><div class="st-ph-card"><i class="bi bi-geo-alt" style="color:var(--alert)"></i><div>New tip<small>Seen near the bus stand · 2 min ago</small></div></div><div class="st-ph-card"><i class="bi bi-geo-alt" style="color:var(--alert)"></i><div>New tip<small>Parked by the mall · 14 min ago</small></div></div><div class="st-ph-btn" style="background:var(--alert);color:#fff">View on map</div>' },
    channels: { k: 'Channels', t: 'Chat · SMS · masked call', l: 'Every conversation runs through SudoTag, so neither side ever sees a phone number.',
      b: ['Real-time chat thread', 'Templated SMS for quick replies', 'Masked voice calls both ways'],
      s: '<p class="st-ph-title">Chat</p><div class="st-ph-card"><div>Your car is blocking my gate<small>Scanner · just now</small></div></div><div class="st-ph-card" style="justify-content:flex-end;background:var(--signal);color:var(--signal-ink)"><div>Coming in 2 minutes!</div></div><div class="st-ph-card"><i class="bi bi-telephone"></i><div>Masked call<small>•••• ••••• hidden</small></div></div>' },
    status: { k: 'Coming soon', t: 'Live Status + privacy', l: "Coming soon. Tell scanners what to expect before they wait: Available, Busy, Driving or Do Not Disturb.",
      b: ['Shown on the scan page', 'Auto-switch while driving', 'DND still lets emergencies through'],
      s: '<p class="st-ph-title">Live Status</p><div class="st-ph-card"><span class="st-dot st-dot--safe"></span><div>Available</div></div><div class="st-ph-card"><span class="st-dot" style="background:var(--amber)"></span><div>Busy</div></div><div class="st-ph-card"><span class="st-dot" style="background:var(--signal-2)"></span><div>Driving</div></div><div class="st-ph-card"><span class="st-dot" style="background:var(--alert)"></span><div>Do Not Disturb</div></div>' },
    ai: { k: 'Coming soon', t: 'Sudo AI', l: "Coming soon. Quick answers about SudoTag and your vehicles, right inside the app.",
      b: ['Ask in plain language', 'Knows the vehicles in your garage', 'Points you to the right screen'],
      s: '<p class="st-ph-title">Sudo AI</p><div class="st-ph-card"><div>How do I use Lost Mode?</div></div><div class="st-ph-card" style="border-color:var(--signal)"><i class="bi bi-stars"></i><div>Open your vehicle, tap Lost Mode and switch it on. Anyone who scans your tag can then send you tips.</div></div><div class="st-ph-btn">Open Lost Mode</div>' },
    order: { k: 'Shop', t: 'Order QR tags', l: 'Got a new vehicle? Order another official SudoTag straight from the app.',
      b: ['Official weatherproof stickers', 'Delivered to your door', 'Activate in two minutes'],
      s: '<p class="st-ph-title">Order tags</p><div class="st-ph-card"><i class="bi bi-qr-code"></i><div>SudoTag sticker<small>Weatherproof</small></div></div><div class="st-ph-card"><i class="bi bi-truck"></i><div>Shipping<small>To your door</small></div></div><div class="st-ph-btn">Buy now</div>' },
    refer: { k: 'Rewards', t: 'Refer & earn', l: 'Share your code and earn rewards when friends tag their vehicles.',
      b: ['Personal invite code', 'Track invites in the app', 'Rewards credited automatically'],
      s: '<p class="st-ph-title">Refer &amp; earn</p><div class="st-ph-card"><i class="bi bi-gift"></i><div>Your code<small class="st-mono">SUDO-7F3K</small></div></div><div class="st-ph-card"><i class="bi bi-people"></i><div>Friends joined<small>Rewards credited</small></div></div><div class="st-ph-btn">Share invite</div>' }
  };
  (function sheet() {
    var dlg = $('#stSheet'); if (!dlg || typeof dlg.showModal !== 'function') return;
    var lastTile = null;
    function open(tile) {
      var f = FEATURES[tile.getAttribute('data-feature')]; if (!f) return;
      lastTile = tile;
      $('#stSheetKicker').textContent = f.k; $('#stSheetTitle').textContent = f.t; $('#stSheetLead').textContent = f.l;
      $('#stSheetList').innerHTML = f.b.map(function (x) { return '<li>' + x + '</li>'; }).join('');
      $('#stSheetScreen').innerHTML = f.s;
      var r = tile.getBoundingClientRect();
      dlg.style.setProperty('--fx', Math.round(r.left + r.width / 2 - window.innerWidth / 2) + 'px');
      dlg.style.setProperty('--fy', Math.round(r.top + r.height / 2 - window.innerHeight / 2) + 'px');
      dlg.classList.remove('is-closing');
      dlg.showModal(); body.classList.add('st-sheet-open');
    }
    function close() {
      if (!dlg.open || dlg.classList.contains('is-closing')) return;
      if (reduce) { dlg.close(); return; }
      dlg.classList.add('is-closing');
      setTimeout(function () { dlg.close(); dlg.classList.remove('is-closing'); }, 250);
    }
    dlg.addEventListener('close', function () { body.classList.remove('st-sheet-open'); if (lastTile) lastTile.focus(); });
    dlg.addEventListener('cancel', function (e) { e.preventDefault(); close(); });
    dlg.addEventListener('click', function (e) { if (e.target === dlg || e.target.closest('[data-close]')) close(); });
    var y0 = null;
    dlg.addEventListener('touchstart', function (e) { y0 = dlg.scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
    dlg.addEventListener('touchmove', function (e) { if (y0 !== null && e.touches[0].clientY - y0 > 110) { y0 = null; close(); } }, { passive: true });
    $$('[data-feature]').forEach(function (t) { t.addEventListener('click', function () { open(t); }); });
  })();

  /* =================================================================
     For every vehicle: scroll-snap carousel + "I drive a…" switcher
     ================================================================= */
  (function vehicles() {
    var track = $('#stVTrack'); if (!track) return;
    var slides = $$('.st-vslide', track), tabs = $$('[data-veh]'), cur = 0;
    function mark(i) {
      cur = i;
      slides.forEach(function (s, k) { s.classList.toggle('is-active', k === i); });
      tabs.forEach(function (b) { b.setAttribute('aria-selected', String(+b.getAttribute('data-veh') === i)); });
    }
    function go(i) {
      i = clamp(i, 0, slides.length - 1);
      var s = slides[i];
      track.scrollTo({ left: s.offsetLeft - (track.clientWidth - s.clientWidth) / 2, behavior: reduce ? 'auto' : 'smooth' });
      mark(i);
    }
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) mark(slides.indexOf(e.target)); });
      }, { root: track, threshold: .6 });
      slides.forEach(function (s) { io.observe(s); });
    }
    tabs.forEach(function (b) { b.addEventListener('click', function () { go(+b.getAttribute('data-veh')); }); });
    $$('[data-veh-step]').forEach(function (b) { b.addEventListener('click', function () { go(cur + (+b.getAttribute('data-veh-step'))); }); });
    track.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') { e.preventDefault(); go(cur + 1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(cur - 1); }
    });
    mark(0);
  })();

  /* =================================================================
     Design your tag: live 3D configurator
     ================================================================= */
  (function designer() {
    var sec = $('#designer'); if (!sec) return;
    var stage = $('#stDzStage'), scene = $('#stDzScene'), card = $('#stDzCard'), stack = $('#stDzStack');
    var veh = $('#stDzVeh'), vehSvg = veh && veh.parentNode, pin = $('#stDzPin'), where = $('#stDzWhere'), backVeh = $('#stDzBackVeh');
    var plateIn = $('#stDzPlate'), plateField = $('#stDzPlateField'), plateNum = $('#stDzPlateNum');
    var count = $('#stDzCount'), buy = $('#stDzBuy'), flipBtn = $('#stDzFlip');
    var sumQty = $('#stDzSumQty'), sumShip = $('#stDzSumShip'), sumTotal = $('#stDzSumTotal'), shipRow = $('#stDzSumShipRow');
    var buyUrl = sec.getAttribute('data-buy-url') || '/buy/';
    var price = parseFloat(sec.getAttribute('data-price')), ship = parseFloat(sec.getAttribute('data-shipping'));
    var VEH = {
      car:     { tint: '#FF7A1A', x: '44%', y: '30%', where: 'Stick it inside the windshield, top corner.' },
      bike:    { tint: '#00E5A8', x: '62%', y: '30%', where: 'Stick it on the headlight visor or fuel tank.' },
      scooter: { tint: '#3D7BFF', x: '46%', y: '52%', where: 'Stick it on the front apron.' },
      auto:    { tint: '#FFB547', x: '40%', y: '40%', where: 'Stick it inside the cabin, passenger side.' },
      taxi:    { tint: '#FFD400', x: '44%', y: '30%', where: 'Stick it on the rear window, facing guests.' },
      truck:   { tint: '#FF4D5E', x: '74%', y: '46%', where: 'Stick it on the cab door or windshield.' }
    };
    var state = { veh: 'car', qty: 1, plate: '' }, rx = -8, ry = -18, flipped = false;

    function money(n) { return '₹' + Math.round(n).toLocaleString('en-IN'); }
    function formatPlate(raw) {
      var v = raw.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 11);
      var m = v.match(/^([A-Z]{0,2})(\d{0,2})([A-Z]{0,3})(\d{0,4})(.*)$/);
      if (!m || m[5]) return v;
      return [m[1], m[2], m[3], m[4]].filter(Boolean).join(' ');
    }
    function setTilt() {
      card.style.setProperty('--rx', rx + 'deg'); card.style.setProperty('--ry', ry + 'deg');
      stack.style.setProperty('--rx', rx + 'deg'); stack.style.setProperty('--ry', ry + 'deg');
      scene.style.setProperty('--shx', (-ry * .6).toFixed(1) + 'px');
      card.style.setProperty('--hx', (50 + ry * 1.5).toFixed(1) + '%');
    }
    function ping() { stage.classList.remove('is-ping'); void stage.offsetWidth; stage.classList.add('is-ping'); }
    function updateLink() {
      var q = new URLSearchParams({ qty: state.qty, vehicle: state.veh });
      if (state.plate) q.set('plate', state.plate.replace(/\s/g, ''));
      buy.href = buyUrl + (buyUrl.indexOf('?') === -1 ? '?' : '&') + q.toString();
    }
    function updateSummary() {
      sumQty.textContent = state.qty + ' × SudoTag' + (isNaN(price) ? '' : ' · ' + money(price * state.qty));
      if (isNaN(price)) { shipRow.hidden = true; sumTotal.textContent = 'Shown at checkout'; return; }
      shipRow.hidden = isNaN(ship);
      if (!isNaN(ship)) sumShip.textContent = ship > 0 ? money(ship) : 'Free';
      var total = price * state.qty + (isNaN(ship) ? 0 : ship);
      if (reduce) { sumTotal.textContent = money(total); return; }
      var from = parseFloat(sumTotal.dataset.v || '0'), t0 = null;
      sumTotal.dataset.v = total;
      (function step(t) {
        if (t0 === null) t0 = t;
        var p = clamp((t - t0) / 500, 0, 1);
        sumTotal.textContent = money(lerp(from, total, easeOut(p)));
        if (p < 1) requestAnimationFrame(step);
      })(performance.now());
    }
    function setVeh(v, animate) {
      if (!VEH[v]) return;
      state.veh = v;
      var d = VEH[v];
      stage.style.setProperty('--tint', d.tint);
      veh.setAttribute('href', '#v-' + v);
      if (animate && !reduce) {
        vehSvg.classList.remove('is-draw'); void vehSvg.offsetWidth; vehSvg.classList.add('is-draw');
        card.classList.remove('is-relabel'); void card.offsetWidth; card.classList.add('is-relabel');
      }
      pin.style.setProperty('--x', d.x); pin.style.setProperty('--y', d.y);
      where.textContent = d.where;
      backVeh.textContent = v;
      var r = $('#stDzForm input[name="veh"][value="' + v + '"]'); if (r) r.checked = true;
      updateLink();
    }
    function setQty(n) {
      state.qty = n;
      var layers = Math.min(n - 1, 4), html = '';
      for (var i = layers; i >= 1; i--) html += '<span style="--i:' + i + '"></span>';
      stack.innerHTML = html;
      count.textContent = '×' + n;
      count.classList.remove('is-bump'); void count.offsetWidth; count.classList.add('is-bump');
      updateSummary(); updateLink();
    }
    function renderPlate() {
      var txt = state.plate || 'KL 11 AB 1234';
      plateNum.classList.toggle('is-empty', !state.plate);
      plateNum.innerHTML = '';
      for (var i = 0; i < txt.length; i++) {
        var c = document.createElement('span'); c.textContent = txt[i] === ' ' ? ' ' : txt[i];
        if (!(state.plate && i === txt.length - 1)) c.style.animation = 'none';
        plateNum.appendChild(c);
      }
    }

    $$('#stDzForm input[name="veh"]').forEach(function (r) { r.addEventListener('change', function () { setVeh(r.value, true); ping(); }); });
    $$('#stDzForm input[name="qty"]').forEach(function (r) { r.addEventListener('change', function () { setQty(+r.value); }); });
    plateIn.addEventListener('input', function () {
      var f = formatPlate(plateIn.value);
      if (plateIn.value !== f) plateIn.value = f;
      state.plate = f; renderPlate(); updateLink(); ping();
      if (!reduce) { plateField.classList.remove('is-snap'); void plateField.offsetWidth; plateField.classList.add('is-snap'); }
    });
    function setFlip(f) {
      flipped = f; card.style.setProperty('--flip', f ? '180deg' : '0deg');
      flipBtn.setAttribute('aria-label', f ? 'Show the front of the tag' : 'Flip the tag');
    }
    flipBtn.addEventListener('click', function () { setFlip(!flipped); });

    /* Drag to rotate; release snaps to the nearest face. Tap flips. */
    var drag = null;
    scene.addEventListener('pointerdown', function (e) {
      drag = { x: e.clientX, y: e.clientY, rx: rx, ry: ry, moved: false };
      try { scene.setPointerCapture(e.pointerId); } catch (err) {}
      scene.classList.add('is-dragging');
    });
    scene.addEventListener('pointermove', function (e) {
      if (!drag) {
        if (!finePointer || reduce) return;
        var r = scene.getBoundingClientRect();
        rx = -8 + ((e.clientY - r.top) / r.height - .5) * -14;
        ry = -18 + ((e.clientX - r.left) / r.width - .5) * 30;
        setTilt();
        return;
      }
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
      ry = drag.ry + dx * .5; rx = clamp(drag.rx - dy * .35, -40, 40); setTilt();
    });
    function endDrag() {
      if (!drag) return;
      var moved = drag.moved; drag = null; scene.classList.remove('is-dragging');
      if (Math.abs(Math.round((ry + 18) / 180)) % 2 === 1) setFlip(!flipped);
      rx = -8; ry = -18; setTilt();
      if (!moved) setFlip(!flipped);
    }
    scene.addEventListener('pointerup', endDrag);
    scene.addEventListener('pointercancel', endDrag);
    scene.addEventListener('pointerleave', function () { if (!drag) { rx = -8; ry = -18; setTilt(); } });

    /* Deep links from the Vehicles section and the hero persona chips */
    document.addEventListener('click', function (e) {
      var a = e.target.closest('[data-design-veh]'); if (!a) return;
      setVeh(a.getAttribute('data-design-veh'), true);
    });
    chips.forEach(function (c) { c.addEventListener('click', function () { setVeh(c.getAttribute('data-persona'), false); }); });

    setTilt(); setVeh('car', false); setQty(1); renderPlate();
  })();

  /* =================================================================
     Lost Mode map: community dots ping a lost bike, tips toast in
     ================================================================= */
  (function lostMap() {
    var map = $('#stLostMap'); if (!map) return;
    var dots = $('.st-lost__dots', map), toasts = $('.st-lost__toasts', map), timer = 0, tick = 0;
    var TIPS = [['Seen near the bus stand', '2 min ago'], ['Parked outside the mall', '6 min ago'], ['Moving towards the beach road', '9 min ago'], ['Spotted at a petrol pump', '12 min ago']];
    function toast(host, icon, text, sub) {
      var t = document.createElement('div'); t.className = 'st-toast';
      t.innerHTML = '<i class="bi ' + icon + '"></i><span>' + text + '<small>' + sub + '</small></span>';
      host.appendChild(t);
      while (host.children.length > 2) host.removeChild(host.firstChild);
      setTimeout(function () { t.classList.add('is-out'); setTimeout(function () { t.remove(); }, 400); }, 4200);
    }
    function addDot() {
      var w = map.clientWidth, h = map.clientHeight, a = Math.random() * Math.PI * 2, r = (.22 + Math.random() * .25) * Math.min(w, h);
      var x = w / 2 + Math.cos(a) * r * 1.3, y = h / 2 + Math.sin(a) * r;
      var d = document.createElement('span'); d.className = 'st-lost__dot';
      d.style.left = x + 'px'; d.style.top = y + 'px';
      d.innerHTML = '<svg width="1" height="1"><line x1="0" y1="0" x2="' + (w / 2 - x) + '" y2="' + (h / 2 - y) + '"/></svg>';
      dots.appendChild(d);
      while (dots.children.length > 8) dots.removeChild(dots.firstChild);
    }
    function step() {
      addDot();
      if (tick++ % 2 === 0) { var tip = TIPS[(tick / 2 | 0) % TIPS.length]; toast(toasts, 'bi-geo-alt-fill', tip[0], 'Community tip · ' + tip[1]); }
    }
    if (reduce) { for (var i = 0; i < 6; i++) addDot(); toast(toasts, 'bi-geo-alt-fill', TIPS[0][0], 'Community tip'); return; }
    whenVisible(map, function () { if (!timer) { step(); timer = setInterval(step, 1500); } }, function () { clearInterval(timer); timer = 0; });
  })();

  /* =================================================================
     Owners figure: starts at 300 and counts DOWN to the real number
     (e.g. 300+ -> 100+) the first time it scrolls into view.
     ================================================================= */
  $$('[data-countdown]').forEach(function (el) {
    var from = +el.getAttribute('data-countdown'), to = +el.getAttribute('data-to');
    if (reduce || !(from > to)) return;
    el.textContent = from + '+';
    var done = false;
    whenVisible(el, function () {
      if (done) return; done = true;
      var t0 = null, D = 1500;
      setTimeout(function () {
        requestAnimationFrame(function f(t) {
          if (t0 === null) t0 = t;
          var p = clamp((t - t0) / D, 0, 1);
          el.textContent = Math.round(from - (from - to) * easeOut(p)) + '+';
          if (p < 1) requestAnimationFrame(f); else el.classList.add('is-done');
        });
      }, 250);
    }, null, '0px 0px -10% 0px');
  });

  /* =================================================================
     Numbers: count up; the "0" counts DOWN from a phone number
     ================================================================= */
  $$('[data-count]').forEach(function (el) {
    var to = +el.getAttribute('data-count'), from = el.getAttribute('data-from'), suffix = el.getAttribute('data-suffix') || '';
    if (reduce) return;
    var done = false;
    whenVisible(el, function () {
      if (done) return; done = true;
      if (from) {
        var digits = String(from), t0 = null, D = 1600;
        (function f(t) {
          if (t0 === null) t0 = t;
          var p = clamp((t - t0) / D, 0, 1), keep = Math.round(digits.length * (1 - easeOut(p)));
          var s = ''; for (var i = 0; i < keep; i++) s += (Math.random() * 10) | 0;
          el.textContent = (s || String(to)) + suffix;
          if (p < 1) requestAnimationFrame(f); else el.textContent = to + suffix;
        })(performance.now());
      } else if (to > 0) {
        var t1 = null;
        (function g(t) {
          if (t1 === null) t1 = t;
          var p = clamp((t - t1) / 1200, 0, 1);
          el.textContent = Math.round(to * easeOut(p)) + suffix;
          if (p < 1) requestAnimationFrame(g);
        })(performance.now());
      }
    });
  });

  /* =================================================================
     Fleet: live map with 40 vehicles on a street grid + alert toasts
     ================================================================= */
  (function fleet() {
    var cv = $('#stFleet'), host = $('#stFleetToasts');
    if (!cv || !cv.getContext) return;
    var ctx = cv.getContext('2d'), w = 0, h = 0, G = 44, cars = [], cols = {};
    function readCols() { cols = { line: cssVar('--line') || '#1F2633', safe: cssVar('--safe'), amber: cssVar('--amber'), alert: cssVar('--alert'), sig: cssVar('--signal') }; }
    readCols(); themeListeners.push(readCols);
    function size() {
      var r = cv.getBoundingClientRect(); w = r.width; h = r.height;
      cv.width = w * DPR; cv.height = h * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      G = Math.max(36, Math.round(w / 12));
      cars = [];
      for (var i = 0; i < 40; i++) {
        var gx = (Math.random() * (w / G)) | 0, gy = 1 + ((Math.random() * (h / G - 1)) | 0);
        cars.push({ x: gx * G, y: gy * G, tx: gx * G, ty: gy * G, sp: .4 + Math.random() * .6, c: i % 9 === 0 ? 'amber' : 'safe', alert: 0 });
      }
    }
    size(); window.addEventListener('resize', size);
    function nextNode(c) {
      var dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]], d = dirs[(Math.random() * 4) | 0];
      c.tx = clamp(c.tx + d[0] * G, 0, Math.floor(w / G) * G); c.ty = clamp(c.ty + d[1] * G, G, Math.floor(h / G) * G);
    }
    function draw(t) {
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = cols.line; ctx.lineWidth = 6; ctx.lineCap = 'round'; ctx.beginPath();
      for (var x = 0; x <= w; x += G) { ctx.moveTo(x, G); ctx.lineTo(x, h); }
      for (var y = G; y <= h; y += G) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
      ctx.stroke();
      for (var i = 0; i < cars.length; i++) {
        var c = cars[i];
        if (!reduce) {
          var dx = c.tx - c.x, dy = c.ty - c.y, dist = Math.abs(dx) + Math.abs(dy);
          if (dist < 1) { c.x = c.tx; c.y = c.ty; nextNode(c); }
          else { c.x += Math.sign(dx) * Math.min(Math.abs(dx), c.sp); c.y += Math.sign(dy) * Math.min(Math.abs(dy), c.sp); }
        }
        var col = c.alert > 0 ? cols.alert : cols[c.c];
        if (c.alert > 0) {
          c.alert -= 1;
          ctx.strokeStyle = cols.alert; ctx.globalAlpha = (c.alert % 60) / 60; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.arc(c.x, c.y, 6 + (60 - c.alert % 60) * .4, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = 1;
        }
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 8;
        ctx.beginPath(); ctx.arc(c.x, c.y, 3.2, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
      }
    }
    var EVENTS = [
      ['bi-bell-fill', 'TN 09 BZ 3306 · blocking dock 3', 'Driver alerted · masked'],
      ['bi-lightbulb', 'KA 05 MN 4420 · headlights on', 'Driver alerted · masked'],
      ['bi-geo-alt', 'KL 11 AB 1234 · Lost Mode tip', 'Seen near the depot'],
      ['bi-chat-dots-fill', 'MH 02 CX 7781 · "Lights are on"', 'Driver replied in chat']
    ];
    var k = 0, ev = 0;
    function fire() {
      var c = cars[(Math.random() * cars.length) | 0]; if (c) c.alert = 180;
      var e = EVENTS[k++ % EVENTS.length];
      var t = document.createElement('div'); t.className = 'st-toast';
      t.innerHTML = '<i class="bi ' + e[0] + '"></i><span>' + e[1] + '<small>' + e[2] + '</small></span>';
      host.appendChild(t);
      while (host.children.length > 2) host.removeChild(host.firstChild);
      setTimeout(function () { t.classList.add('is-out'); setTimeout(function () { t.remove(); }, 400); }, 4600);
    }
    if (reduce) { draw(0); fire(); return; }
    loop(cv, draw);
    whenVisible(cv, function () { if (!ev) { fire(); ev = setInterval(fire, 2800); } }, function () { clearInterval(ev); ev = 0; });
  })();

  /* Fleet lead form → WhatsApp (nothing stored on this page) */
  var lead = $('#stLead');
  if (lead) lead.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = new FormData(lead);
    if (!String(f.get('name') || '').trim()) { lead.querySelector('[name=name]').focus(); return; }
    var msg = 'Hi SudoTag, please add me to the Fleet early-access list.\nName: ' + f.get('name') + '\nCompany: ' + (f.get('company') || '-') +
      '\nFleet size: ' + f.get('size') + '\nPhone: ' + (f.get('phone') || '-');
    window.open('https://wa.me/917907965255?text=' + encodeURIComponent(msg), '_blank', 'noopener');
  });

  /* =================================================================
     Stories: success burst when feedback.js reports success
     ================================================================= */
  var fbAlert = $('#fb-form-alert'), review = $('#stReview');
  if (fbAlert && review && 'MutationObserver' in window) {
    new MutationObserver(function () {
      if (/feedback-alert--success/.test(fbAlert.className) && !fbAlert.hidden) {
        review.classList.remove('is-burst'); void review.offsetWidth; review.classList.add('is-burst');
      }
    }).observe(fbAlert, { attributes: true, attributeFilter: ['class', 'hidden'] });
  }

  /* =================================================================
     Stories: "signal strength" summary computed from approved reviews
     ================================================================= */
  (function score() {
    var box = $('#stScore'); if (!box) return;
    var avgEl = $('[data-score-avg]', box), nEl = $('[data-score-n]', box), nounEl = $('[data-score-noun]', box);
    var bars = $$('[data-score-bars] i', box), rows = $$('[data-score-dist] li', box);
    function paint(ratings) {
      var n = ratings.length, sum = 0, counts = [0, 0, 0, 0, 0, 0];
      ratings.forEach(function (r) { r = clamp(Math.round(r), 1, 5); sum += r; counts[r]++; });
      var avg = n ? sum / n : 0;
      box.classList.toggle('is-empty', !n);
      if (avgEl) avgEl.textContent = n ? avg.toFixed(1) : '–';
      if (nEl) nEl.textContent = n;
      if (nounEl) nounEl.textContent = n === 1 ? 'review' : 'reviews';
      bars.forEach(function (b, i) { b.classList.toggle('is-on', n && avg >= i + .5); });
      rows.forEach(function (li) {
        var r = +li.getAttribute('data-r'), c = counts[r] || 0;
        li.querySelector('em').textContent = c;
        li.querySelector('b').style.width = (n ? c / n * 100 : 0) + '%';
      });
    }
    paint($$('#feedback-slides .st-msg[data-rating]').map(function (m) { return +m.getAttribute('data-rating'); }));
    document.addEventListener('st:feedback', function (e) {
      paint((e.detail || []).map(function (fb) { return Number(fb.rating) || 0; }).filter(Boolean));
    });
    /* "Write a review" opens the form and scrolls to it */
    $$('[data-open-review]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var d = $('#stReview'); if (!d) return;
        e.preventDefault(); d.open = true;
        d.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
        var f = $('#fb-name'); if (f) setTimeout(function () { f.focus({ preventScroll: true }); }, 500);
      });
    });
  })();

  /* =================================================================
     Review composer: live preview, rating word, character count.
     Submission itself stays in feedback.js.
     ================================================================= */
  (function composer() {
    var form = $('#landing-feedback-form'), prev = $('#stPreview'); if (!form || !prev) return;
    var nameIn = $('#fb-name'), msgIn = $('#fb-message'), rateIn = $('#fb-rating');
    var count = $('[data-fb-count]'), word = $('[data-rate-word]');
    var pName = $('[data-prev-name]', prev), pAv = $('[data-prev-av]', prev), pText = $('[data-prev-text]', prev);
    var pScore = $('[data-prev-score]', prev), pBars = $$('[data-prev-bars] i', prev);
    var WORDS = ['Tap a bar', 'Weak signal', 'Fair signal', 'Good signal', 'Strong signal', 'Full signal'];
    var EMPTY = pText.textContent;
    function sync() {
      var n = nameIn.value.trim(), m = msgIn.value.trim(), r = +rateIn.value || 0;
      pName.textContent = n || 'Your name';
      pAv.textContent = n ? n.charAt(0).toUpperCase() : '?';
      pText.textContent = m || EMPTY;
      pText.classList.toggle('is-empty', !m);
      pScore.textContent = (r || '–') + '/5';
      pBars.forEach(function (b, i) { b.classList.toggle('is-on', i < r); });
      if (word) { word.textContent = WORDS[r]; word.classList.toggle('is-set', r > 0); }
      if (count) { count.textContent = msgIn.value.length + ' / 1000'; count.classList.toggle('is-near', msgIn.value.length > 900); }
    }
    form.addEventListener('input', sync);
    form.addEventListener('click', function (e) { if (e.target.closest('.feedback-star')) sync(); });
    form.addEventListener('reset', function () { setTimeout(sync, 0); });
    sync();
  })();

  /* =================================================================
     Help: search-as-you-type FAQ
     ================================================================= */
  (function faq() {
    var input = $('#stFaqSearch'), list = $('#stFaq'), empty = $('#stFaqEmpty');
    if (!input || !list) return;
    var items = $$('.st-qa', list).map(function (d) { return { el: d, s: d.querySelector('summary'), raw: d.querySelector('summary').textContent, text: d.textContent.toLowerCase() }; });
    function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase(), hits = 0;
      items.forEach(function (it) {
        var ok = !q || it.text.indexOf(q) !== -1;
        it.el.hidden = !ok; if (ok) hits++;
        if (q && ok) {
          var i = it.raw.toLowerCase().indexOf(q);
          it.s.innerHTML = i === -1 ? esc(it.raw) : esc(it.raw.slice(0, i)) + '<mark>' + esc(it.raw.slice(i, i + q.length)) + '</mark>' + esc(it.raw.slice(i + q.length));
          if (hits === 1) it.el.open = true;
        } else it.s.textContent = it.raw;
      });
      if (empty) empty.hidden = hits > 0;
    });
  })();

  /* =================================================================
     Offers slider (Swiper, config from inline JSON)
     ================================================================= */
  function initSwipers() {
    if (typeof window.Swiper === 'undefined') return;
    $$('.init-swiper').forEach(function (el) {
      var node = el.querySelector('.swiper-config'), cfg = {};
      try { cfg = JSON.parse(node ? node.textContent : '{}'); } catch (e) {}
      if (reduce) delete cfg.autoplay;
      new window.Swiper(el, cfg);
    });
  }
  if (document.readyState === 'complete') initSwipers(); else window.addEventListener('load', initSwipers);

  /* =================================================================
     App links → App Store on iOS
     ================================================================= */
  if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) {
    $$('[data-app-link]').forEach(function (a) { a.href = 'https://apps.apple.com/in/app/sudotag/id6761091033'; });
  }

  /* =================================================================
     Viewfinder cursor (mouse / trackpad only)
     dot = the SudoTag beacon; corners trail it, lock onto buttons,
     turn into a scanner over stickers / QR, ENCRYPT over the number wall.
     ================================================================= */
  (function cursor() {
    if (!finePointer || !window.requestAnimationFrame) return;
    var el = document.createElement('div');
    el.className = 'st-cursor'; el.setAttribute('aria-hidden', 'true');
    el.innerHTML = '<span class="st-cursor__frame"><i></i><i></i><i></i><i></i><span class="st-cursor__line"></span></span>' +
      '<span class="st-cursor__dot"></span><span class="st-cursor__label st-mono"></span>';
    body.appendChild(el);
    root.classList.add('st-cursor-on');
    /* Modal <dialog>s render in the browser's top layer, above any z-index.
       The cursor joins the top layer as a manual popover and is re-raised
       whenever a dialog opens, so it always stays above popups. Without
       popover support, fall back to the native pointer while a dialog is open. */
    var canPop = typeof el.showPopover === 'function';
    if (canPop) el.setAttribute('popover', 'manual');
    function lift() {
      var modal = !!document.querySelector('dialog[open]');
      if (!canPop) { root.classList.toggle('st-cursor-on', !modal); el.style.display = modal ? 'none' : ''; return; }
      try { if (el.matches(':popover-open')) el.hidePopover(); el.showPopover(); } catch (err) {}
    }
    lift();
    if ('MutationObserver' in window) new MutationObserver(function (ms) {
      for (var i = 0; i < ms.length; i++) if (ms[i].target.tagName === 'DIALOG') { setTimeout(lift, 0); return; }
    }).observe(body, { subtree: true, attributes: true, attributeFilter: ['open'] });
    var frame = el.firstChild, dot = el.children[1], label = el.children[2];
    var LOCK = 'a[href], button:not([disabled]), [role="button"], [role="tab"], [role="radio"], label.st-btn, summary, .st-tile, [data-cursor="lock"]';
    var SCAN = '[data-cursor="scan"], .st-tag3d, .st-cam, .g-qr, .g-stick, .st-sc--glass, .st-dz__stage';
    var TEXT = 'input, textarea, select, [contenteditable="true"]';
    var mx = -100, my = -100, x = -100, y = -100, w = 34, h = 34, shown = false, mode = '', target = null, lab = '';
    var hero = $('#hero'), wall = $('#stNumwall');

    function setMode(m, t, text) {
      target = t;
      if (m !== mode) { el.classList.remove('is-' + mode); if (m) el.classList.add('is-' + m); mode = m; }
      if (text !== lab) { lab = text; label.textContent = text; }
    }
    function resolve(node) {
      if (!node || !node.closest) return setMode('', null, '');
      if (node.closest(TEXT)) return setMode('text', null, '');
      var s = node.closest(SCAN);
      var l = node.closest(LOCK);
      if (l && (!s || s.contains(l))) {
        var r = l.getBoundingClientRect();
        if (r.width < 560 && r.height < 280) return setMode('lock', l, l.getAttribute('data-cursor-label') || '');
      }
      if (s) return setMode('scan', s, s.getAttribute('data-cursor-label') || 'Scan');
      if (wall && hero && hero.contains(node) && !node.closest('.st-hero__copy, .st-beacon-stage')) return setMode('enc', null, 'Encrypt');
      setMode('', null, '');
    }
    document.addEventListener('pointermove', function (e) {
      if (e.pointerType && e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
      mx = e.clientX; my = e.clientY;
      if (!shown) { shown = true; x = mx - w / 2; y = my - h / 2; el.classList.add('is-on'); }
      resolve(e.target);
    }, { passive: true });
    document.addEventListener('pointerdown', function () {
      el.classList.remove('is-press'); void el.offsetWidth; el.classList.add('is-press');
      var ping = document.createElement('span'); ping.className = 'st-cursor__ping';
      ping.style.transform = 'translate(' + mx + 'px,' + my + 'px)';
      el.appendChild(ping); setTimeout(function () { ping.remove(); }, 700);
    });
    document.addEventListener('mouseleave', function () { shown = false; el.classList.remove('is-on'); });
    window.addEventListener('blur', function () { shown = false; el.classList.remove('is-on'); });
    /* the page scrolls under a still mouse: re-check what is under it */
    window.addEventListener('scroll', function () { if (shown) resolve(document.elementFromPoint(mx, my)); }, { passive: true });

    (function tick() {
      var tx, ty, tw, th, k;
      if (mode === 'lock' && target && target.isConnected) {
        var r = target.getBoundingClientRect(), pad = 6;
        tx = r.left - pad; ty = r.top - pad; tw = r.width + pad * 2; th = r.height + pad * 2; k = .3;
      } else if (mode === 'scan') {
        tw = th = 72; tx = mx - 36; ty = my - 36; k = .22;
      } else if (mode === 'enc') {
        tw = th = 52; tx = mx - 26; ty = my - 26; k = .2;
      } else {
        tw = th = 34; tx = mx - 17; ty = my - 17; k = reduce ? 1 : .2;
      }
      x += (tx - x) * k; y += (ty - y) * k; w += (tw - w) * k; h += (th - h) * k;
      frame.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px)';
      frame.style.width = w.toFixed(1) + 'px'; frame.style.height = h.toFixed(1) + 'px';
      dot.style.transform = 'translate(' + mx + 'px,' + my + 'px)';
      label.style.transform = 'translate(' + (x + w / 2).toFixed(1) + 'px,' + (y + h + 8).toFixed(1) + 'px)';
      requestAnimationFrame(tick);
    })();
  })();

  /* =================================================================
     Page transition: signal scan-line wipe on internal navigation
     ================================================================= */
  var wipe = $('#stWipe');
  if (wipe && !reduce) {
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[href]');
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (a.target && a.target !== '_self') return;
      if (a.hasAttribute('download')) return;
      var url; try { url = new URL(a.href, location.href); } catch (err) { return; }
      if (url.origin !== location.origin || !/^https?:$/.test(url.protocol)) return;
      if (url.pathname === location.pathname && url.search === location.search) return; // in-page anchor
      e.preventDefault();
      wipe.classList.add('is-on');
      setTimeout(function () { location.href = url.href; }, 460);
    });
    window.addEventListener('pageshow', function () { wipe.classList.remove('is-on'); });
  }

  /* Live reduced-motion change → reload behaviour cleanly */
  if (mqReduce.addEventListener) mqReduce.addEventListener('change', function () { reduce = mqReduce.matches; });
})();
