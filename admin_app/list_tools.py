"""Search, filter and CSV export helpers shared by the admin list screens."""

from __future__ import annotations

import csv
from datetime import datetime
from urllib.parse import urlencode

from django.http import HttpResponse

from . import analytics


def get_path(row, path):
    """'address.city' -> row['address']['city'] (missing parts -> '')."""
    cur = row
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return ''
        cur = cur.get(part)
        if cur is None:
            return ''
    return cur


def matches(row, query, fields):
    """True when every word of `query` appears in at least one of `fields` (case-insensitive)."""
    words = [w for w in (query or '').lower().split() if w]
    if not words:
        return True
    hay = ' '.join(str(get_path(row, f)) for f in fields).lower()
    hay_digits = ''.join(ch for ch in hay if ch.isdigit() or ch == ' ')
    for w in words:
        if w in hay:
            continue
        digits = ''.join(ch for ch in w if ch.isdigit())
        # Phone numbers: "+91 98765 43210" should match "9876543210".
        if digits and len(digits) >= 4 and digits in hay_digits.replace(' ', ''):
            continue
        return False
    return True


def query_string(request, drop=('page', 'export')):
    """Current GET params minus `drop`, ending in '&' when non-empty, for pagination links."""
    params = [(k, v) for k, v in request.GET.items() if k not in drop and v != '']
    return urlencode(params) + '&' if params else ''


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, datetime) or hasattr(value, 'to_datetime'):
        dt = analytics.to_ist(value)
        return dt.strftime('%Y-%m-%d %H:%M') if dt else ''
    if isinstance(value, dict):
        value = ', '.join(str(v) for v in value.values() if v not in (None, ''))
    if isinstance(value, (list, tuple)):
        value = ', '.join(str(v) for v in value)
    text = str(value)
    # Stop spreadsheet apps from running cell contents as formulas.
    if text[:1] in ('=', '+', '-', '@', '\t', '\r'):
        text = "'" + text
    return text


def csv_response(filename, columns, rows):
    """columns: [(header, path or callable)]. Returns a downloadable CSV."""
    stamp = datetime.now(analytics.IST).strftime('%Y%m%d-%H%M')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}-{stamp}.csv"'
    response.write('﻿')  # so Excel reads UTF-8 (₹, names) correctly
    writer = csv.writer(response)
    writer.writerow([h for h, _ in columns])
    for row in rows:
        writer.writerow([_cell(get(row) if callable(get) else get_path(row, get)) for _, get in columns])
    return response


def sort_key_time(field):
    def key(row):
        dt = analytics.to_ist(get_path(row, field))
        return dt.timestamp() if dt else 0
    return key
