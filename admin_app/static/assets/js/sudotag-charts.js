/*
 * SudoTag admin charts: thin Chart.js wrappers in the SudoTag style.
 * Needs Chart.js 4 loaded first. Used by analytics.html and dashboard.html.
 */
(function () {
  'use strict';

  var css = getComputedStyle(document.body);
  function token(name, fallback) { return (css.getPropertyValue(name) || '').trim() || fallback; }

  var C = {
    series: [token('--viz-1', '#FF7A1A'), token('--viz-2', '#2a78d6'), token('--viz-3', '#1baf7a')],
    grid: token('--viz-grid', '#EEF0F3'),
    axis: token('--viz-axis', '#D5D9E0'),
    muted: '#6B7385',
    ink: '#0B0D12',
    surface: '#FFFFFF'
  };

  var inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
  function fmt(v, money) { return (money ? '₹' : '') + inr.format(v || 0); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  if (window.Chart) {
    Chart.defaults.font.family = 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif';
    Chart.defaults.font.size = 11;
    Chart.defaults.color = C.muted;
    Chart.defaults.animation.duration = 700;
  }

  // Vertical hairline under the cursor for line/area charts.
  var crosshair = {
    id: 'stCrosshair',
    afterDatasetsDraw: function (chart) {
      var a = chart.tooltip && chart.tooltip.getActiveElements();
      if (!a || !a.length || chart.config.type !== 'line') return;
      var x = a[0].element.x, area = chart.chartArea, ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, area.top);
      ctx.lineTo(x, area.bottom);
      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(11,13,18,0.25)';
      ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.restore();
    }
  };

  // Dark HTML tooltip that matches the panel instead of the default canvas one.
  function htmlTooltip(money) {
    return function (context) {
      var chart = context.chart, tip = context.tooltip;
      var host = chart.canvas.parentNode;
      var el = host.querySelector('.an-tip');
      if (!el) { el = document.createElement('div'); el.className = 'an-tip'; el.setAttribute('role', 'presentation'); host.appendChild(el); }
      if (!tip.opacity) { el.classList.remove('show'); return; }
      var rows = (tip.dataPoints || []).map(function (p) {
        var color = p.dataset.borderColor || p.dataset.backgroundColor;
        if (Array.isArray(color)) color = color[p.dataIndex];
        return '<div class="r"><i style="background:' + color + '"></i>' + esc(p.dataset.label) +
          '<b>' + fmt(p.raw, p.dataset.money !== undefined ? p.dataset.money : money) + '</b></div>';
      }).join('');
      el.innerHTML = '<div class="t">' + esc(tip.title && tip.title[0] || '') + '</div>' + rows;
      var x = tip.caretX, w = host.clientWidth;
      el.style.left = Math.min(Math.max(x, 70), w - 70) + 'px';
      el.style.top = tip.caretY + 'px';
      el.classList.add('show');
    };
  }

  function baseOptions(opts) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      layout: { padding: { top: 6, right: 4 } },
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false, external: htmlTooltip(opts.money) }
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: C.axis },
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: opts.maxTicks || (window.innerWidth < 600 ? 4 : 8) }
        },
        y: {
          beginAtZero: true,
          grid: { color: C.grid, drawTicks: false },
          border: { display: false },
          ticks: {
            padding: 8, maxTicksLimit: 5, precision: 0,
            callback: function (v) { return fmt(v, opts.money); }
          }
        }
      }
    };
  }

  function legend(el, chart, totals, money) {
    if (!el) return;
    el.innerHTML = '';
    chart.data.datasets.forEach(function (ds, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('aria-pressed', 'true');
      b.title = 'Show or hide ' + ds.label;
      b.innerHTML = '<span class="sw" style="background:' + ds.borderColor + '"></span>' + esc(ds.label) +
        (totals ? ' <span class="total">' + fmt(totals[i], money) + '</span>' : '');
      b.addEventListener('click', function () {
        var visible = chart.isDatasetVisible(i);
        chart.setDatasetVisibility(i, !visible);
        b.setAttribute('aria-pressed', String(!visible));
        chart.update();
      });
      el.appendChild(b);
    });
  }

  function sum(a) { return a.reduce(function (s, v) { return s + (v || 0); }, 0); }

  /** Line chart. cfg: {labels, series: [{label, data}], money, fill, legend: element, totals: bool} */
  function line(canvas, cfg) {
    if (!canvas || !window.Chart) return null;
    var ctx = canvas.getContext('2d');
    var datasets = cfg.series.map(function (s, i) {
      var color = s.color || C.series[i % C.series.length];
      var ds = {
        label: s.label, data: s.data, borderColor: color, backgroundColor: color,
        borderWidth: 2, tension: cfg.smooth ? 0.35 : 0, pointRadius: 0, pointHoverRadius: 4,
        pointHoverBorderWidth: 2, pointHoverBorderColor: C.surface, pointHoverBackgroundColor: color,
        fill: false
      };
      if (cfg.fill) {
        var g = ctx.createLinearGradient(0, 0, 0, canvas.parentNode.clientHeight || 260);
        g.addColorStop(0, hexA(color, 0.22));
        g.addColorStop(1, hexA(color, 0));
        ds.backgroundColor = g;
        ds.fill = 'origin';
      }
      return ds;
    });
    var options = baseOptions(cfg);
    if (cfg.zero === false) options.scales.y.beginAtZero = false;
    var chart = new Chart(canvas, {
      type: 'line',
      data: { labels: cfg.labels, datasets: datasets },
      options: options,
      plugins: [crosshair]
    });
    legend(cfg.legend, chart, cfg.totals ? cfg.series.map(function (s) { return sum(s.data); }) : null, cfg.money);
    return chart;
  }

  /** Bar chart over time. cfg: {labels, label, data, money, color} */
  var SOFT = '#FFB27A', STRONG = '#E5640A';

  function peakIndex(data) {
    var best = -1, max = 0;
    data.forEach(function (v, i) { if (v > max) { max = v; best = i; } });
    return best;
  }

  /** Soft rounded bars; the busiest bar is drawn darker. cfg: {labels, label, data, money} */
  function bars(canvas, cfg) {
    if (!canvas || !window.Chart) return null;
    var opts = baseOptions(cfg);
    opts.scales.y.grid.color = C.grid;
    opts.scales.y.ticks.maxTicksLimit = 4;
    opts.scales.x.border = { display: false };
    var chart = new Chart(canvas, {
      type: 'bar',
      data: { labels: cfg.labels, datasets: [dataset(cfg.label, cfg.data, cfg.money)] },
      options: opts
    });
    return chart;
  }

  function dataset(label, data, money) {
    var peak = peakIndex(data);
    return {
      label: label, data: data, money: money,
      backgroundColor: data.map(function (_, i) { return i === peak ? STRONG : SOFT; }),
      hoverBackgroundColor: STRONG,
      borderColor: STRONG,
      borderRadius: 6, borderSkipped: false,
      maxBarThickness: 22, categoryPercentage: 0.82, barPercentage: 0.86,
      minBarLength: 0
    };
  }

  /**
   * One metric at a time, picked with a small switch.
   * cfg: {labels, series: [{label, data, noun}], switchEl, summaryEl, money}
   */
  function metricBars(canvas, cfg) {
    if (!canvas || !window.Chart) return null;
    var chart = bars(canvas, { labels: cfg.labels, label: cfg.series[0].label, data: cfg.series[0].data, money: cfg.money });
    function summary(s) {
      if (!cfg.summaryEl) return;
      var total = sum(s.data), peak = peakIndex(s.data);
      cfg.summaryEl.innerHTML =
        '<span class="an-sum-num">' + fmt(total, cfg.money) + '</span>' +
        '<span class="an-sum-text">' + esc(s.noun || s.label.toLowerCase()) +
        (peak >= 0 ? ' · busiest ' + esc(cfg.labels[peak]) + ' (' + fmt(s.data[peak], cfg.money) + ')' : ' · none yet') + '</span>';
    }
    function pick(i) {
      var s = cfg.series[i];
      chart.data.datasets = [dataset(s.label, s.data, cfg.money)];
      chart.update();
      summary(s);
      if (cfg.switchEl) cfg.switchEl.querySelectorAll('button').forEach(function (b, j) { b.setAttribute('aria-pressed', String(j === i)); });
    }
    if (cfg.switchEl) {
      cfg.switchEl.innerHTML = '';
      cfg.series.forEach(function (s, i) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = s.label;
        b.addEventListener('click', function () { pick(i); });
        cfg.switchEl.appendChild(b);
      });
    }
    pick(0);
    return chart;
  }

  /** Tiny column chart for KPI tiles; the latest period is drawn darker. */
  function spark(svg, data, color) {
    if (!svg || !data || !data.length) return;
    var w = 200, h = 36, gap = data.length > 40 ? 1 : 2;
    var max = Math.max.apply(null, data.concat([1]));
    var bw = Math.max((w - gap * (data.length - 1)) / data.length, 1);
    var out = '';
    data.forEach(function (v, i) {
      var bh = v ? Math.max((v / max) * (h - 2), 3) : 2;
      var x = i * (bw + gap);
      var fill = v ? (i === data.length - 1 ? STRONG : SOFT) : '#ECEEF2';
      out += '<rect x="' + x.toFixed(1) + '" y="' + (h - bh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="' + Math.min(bw / 2, 2).toFixed(1) + '" fill="' + fill + '"/>';
    });
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.innerHTML = out;
  }

  function hexA(hex, a) {
    var h = hex.replace('#', '');
    if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(h, 16);
    return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  // "Table" / "Chart" toggles: <button class="an-toggle" data-view-toggle="growth"> swaps
  // [data-view="growth-chart"] and [data-view="growth-table"].
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-view-toggle]');
    if (!b) return;
    var key = b.getAttribute('data-view-toggle');
    var chart = document.querySelector('[data-view="' + key + '-chart"]');
    var table = document.querySelector('[data-view="' + key + '-table"]');
    if (!chart || !table) return;
    var showTable = table.hidden;
    table.hidden = !showTable;
    chart.hidden = showTable;
    b.textContent = showTable ? 'Chart' : 'Table';
    b.setAttribute('aria-pressed', String(showTable));
  });

  window.STCharts = { line: line, bars: bars, metricBars: metricBars, spark: spark, colors: C, fmt: fmt };
})();
