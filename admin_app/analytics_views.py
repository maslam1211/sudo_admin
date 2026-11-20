"""Analytics page: growth, customers, vehicles, QR stock, revenue and Civic Sense in charts."""

from __future__ import annotations

import logging

from django.shortcuts import redirect, render
from django.urls import reverse

from . import analytics

logger = logging.getLogger(__name__)


def _get_db():
    from .views import db
    return db


HEAT_STEPS = 5


def bars(pairs):
    """[(label, n)] -> [{'label', 'value', 'pct'}] with widths relative to the largest bar."""
    top = max((n for _, n in pairs), default=0) or 1
    return [{'label': label, 'value': n, 'pct': round(n / top * 100, 1)} for label, n in pairs]


def decorate(stats):
    """Adds bar widths and heatmap shade levels the template can use directly."""
    for key in ('cities', 'platforms', 'versions', 'vehicle_types', 'makes'):
        stats[key] = bars(stats[key])
    stats['qr']['wait_bins'] = bars(stats['qr']['wait_bins'])
    for key in ('status', 'channels'):
        stats['revenue'][key] = bars(stats['revenue'][key])
    for key in ('categories', 'states'):
        stats['civic'][key] = bars(stats['civic'][key])
    stats['smart']['categories'] = bars(stats['smart']['categories'])

    heat = stats['heatmap']
    peak = heat['max'] or 1
    heat['grid'] = [
        {'day': day, 'cells': [
            {'value': v, 'level': 0 if not v else max(1, -(-v * HEAT_STEPS // peak)), 'hour': heat['cols'][i]}
            for i, v in enumerate(row)]}
        for day, row in zip(heat['rows'], heat['cells'])
    ]
    eng = stats['engagement']
    total = eng['total'] or 1
    eng['rows'] = [
        {'label': 'Last 24 hours', 'value': eng['day'], 'pct': round(eng['day'] / total * 100)},
        {'label': 'Last 7 days', 'value': eng['week'], 'pct': round(eng['week'] / total * 100)},
        {'label': 'Last 30 days', 'value': eng['month'], 'pct': round(eng['month'] / total * 100)},
    ]
    return stats


def analytics_page(request):
    if not request.session.get('admin'):
        return redirect('admin_login')

    range_key, days = analytics.parse_range(request.GET.get('range'))
    error = None
    try:
        raw = analytics.load(_get_db(), fresh=request.GET.get('refresh') == '1')
        stats = analytics.compute(raw, days)
        loaded_at = raw.get('loaded_at')
    except Exception:
        logger.exception('analytics page failed')
        stats, loaded_at = analytics.compute({}, days), None
        error = 'Could not load data from Firebase. Showing empty charts; try Refresh.'

    notes = analytics.resolve(analytics.insights(stats))
    decorate(stats)
    for k in stats['kpis']:
        k['url'] = reverse(k['href']) if k.get('href') else ''

    return render(request, 'analytics.html', {
        'stats': stats,
        'notes': notes,
        'range_key': range_key,
        'ranges': [('7', '7D'), ('30', '30D'), ('90', '90D'), ('365', '1Y'), ('all', 'All')],
        'loaded_at': loaded_at,
        'error': error,
    })
