/*
 * SudoTag admin UI touches, loaded on every admin page by base.html:
 *  - Command palette (Ctrl/Cmd + K): jump to any page listed in the sidebar.
 *  - Count-up for headline numbers.
 *  - Staggered fade-in for cards.
 * Everything respects prefers-reduced-motion.
 */
(function () {
  'use strict';

  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------- palette
  var dialog = document.getElementById('stPalette');
  var input = document.getElementById('stPaletteInput');
  var list = document.getElementById('stPaletteList');
  var openers = document.querySelectorAll('[data-palette-open]');
  var items = [];
  var shown = [];
  var cursor = 0;
  var lastFocus = null;

  function buildIndex() {
    var section = '';
    document.querySelectorAll('#sidebar .sidebar-section, #sidebar .sidebar-menu-link').forEach(function (el) {
      if (el.classList.contains('sidebar-section')) { section = el.textContent.trim(); return; }
      var label = (el.querySelector('span') || el).textContent.trim();
      var icon = el.querySelector('i');
      if (!label || !el.getAttribute('href')) return;
      items.push({
        label: label,
        section: section,
        href: el.getAttribute('href'),
        icon: icon ? icon.className : 'fas fa-arrow-right',
        danger: el.classList.contains('delete-data-link')
      });
    });
  }

  function score(item, q) {
    if (!q) return 1;
    var label = item.label.toLowerCase();
    if (label.indexOf(q) === 0) return 5;
    if (label.split(/\s+/).some(function (w) { return w.indexOf(q) === 0; })) return 4;
    if (label.indexOf(q) > -1) return 3;
    if (item.section.toLowerCase().indexOf(q) > -1) return 2;
    // initials, e.g. "gqr" -> Generate QR
    var initials = label.split(/\s+/).map(function (w) { return w[0]; }).join('');
    return q.length > 1 && initials.indexOf(q) === 0 ? 1 : 0;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function render() {
    var q = input.value.trim().toLowerCase();
    shown = items.map(function (it) { return { it: it, s: score(it, q) }; })
      .filter(function (x) { return x.s > 0; })
      .sort(function (a, b) { return b.s - a.s; })
      .map(function (x) { return x.it; });
    cursor = Math.min(cursor, Math.max(shown.length - 1, 0));
    if (!shown.length) {
      list.innerHTML = '<li class="st-palette-empty">No page matches "' + esc(input.value) + '"</li>';
      input.removeAttribute('aria-activedescendant');
      return;
    }
    list.innerHTML = shown.map(function (it, i) {
      return '<li role="option" id="stp-' + i + '" aria-selected="' + (i === cursor) + '" data-i="' + i + '"' + (it.danger ? ' class="is-danger"' : '') + '>' +
        '<i class="' + esc(it.icon) + '"></i><span class="l">' + esc(it.label) + '</span><span class="s">' + esc(it.section) + '</span></li>';
    }).join('');
    input.setAttribute('aria-activedescendant', 'stp-' + cursor);
    var active = list.querySelector('[aria-selected="true"]');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  function open() {
    if (!dialog) return;
    lastFocus = document.activeElement;
    dialog.hidden = false;
    document.body.classList.add('st-palette-open');
    input.value = '';
    cursor = 0;
    render();
    setTimeout(function () { input.focus(); }, 10);
  }

  function close() {
    if (!dialog || dialog.hidden) return;
    dialog.hidden = true;
    document.body.classList.remove('st-palette-open');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function go(i) {
    var it = shown[i];
    if (it) window.location.href = it.href;
  }

  if (dialog && input && list) {
    buildIndex();
    openers.forEach(function (b) { b.addEventListener('click', open); });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) close(); });
    input.addEventListener('input', function () { cursor = 0; render(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { cursor = Math.min(cursor + 1, shown.length - 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { cursor = Math.max(cursor - 1, 0); render(); e.preventDefault(); }
      else if (e.key === 'Enter') { go(cursor); e.preventDefault(); }
      else if (e.key === 'Escape') { close(); e.preventDefault(); }
    });
    list.addEventListener('mousemove', function (e) {
      var li = e.target.closest('[data-i]');
      if (li && +li.dataset.i !== cursor) { cursor = +li.dataset.i; render(); }
    });
    list.addEventListener('click', function (e) {
      var li = e.target.closest('[data-i]');
      if (li) go(+li.dataset.i);
    });
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); dialog.hidden ? open() : close(); }
      else if (e.key === '/' && !/input|textarea|select/i.test((document.activeElement || {}).tagName || '') && dialog.hidden) { e.preventDefault(); open(); }
    });
    var isMac = /Mac|iPhone|iPad/.test(navigator.platform || '');
    document.querySelectorAll('[data-kbd-mod]').forEach(function (k) { k.textContent = isMac ? '⌘' : 'Ctrl'; });
  }

  // ---------------------------------------------------------------- count-up
  function countUp(el) {
    var text = el.textContent.trim();
    var m = text.match(/^([^\d-]*)([\d,]+(?:\.\d+)?)(.*)$/);
    if (!m) return;
    var target = parseFloat(m[2].replace(/,/g, ''));
    if (!isFinite(target) || target < 2) return;
    var decimals = (m[2].split('.')[1] || '').length;
    var fmt = new Intl.NumberFormat('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    var start = null, dur = 800;
    el.textContent = m[1] + fmt.format(0) + m[3];
    function step(t) {
      if (start === null) start = t;
      var p = Math.min((t - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = m[1] + fmt.format(target * eased) + m[3];
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = text;
    }
    requestAnimationFrame(step);
  }

  if (!reduce) {
    document.querySelectorAll('[data-count], .an-kpi-value, .db-today b, .an-hero-num').forEach(function (el) {
      // Only the first text node is animated, so nested markup like <small> stays put.
      if (el.children.length) return;
      countUp(el);
    });

  }
})();
