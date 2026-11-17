"""
Firebase usage and cost for the admin panel.

Two sources:

* Usage (always available): Google Cloud Monitoring time series for the
  project — Firestore reads/writes/deletes/storage, Cloud Functions calls and
  Cloud Storage bytes. Cost is *estimated* from list prices after free quota.
  Needs the service account to have roles/monitoring.viewer (it does).

* Exact bill (optional): the Cloud Billing export in BigQuery. Set
  FIREBASE_BILLING_EXPORT_TABLE in .env to the export table, e.g.
  ``my-project.billing.gcp_billing_export_v1_0123AB_456CDE_789EF0``.
  The service account needs BigQuery Job User on the project that holds the
  table and BigQuery Data Viewer on the dataset.

Firebase resets daily free limits at midnight US Pacific time, so days here
are Pacific days.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from collections import defaultdict

import pytz
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

PACIFIC = pytz.timezone('America/Los_Angeles')
CACHE_SECONDS = 15 * 60
GIB = 1024 ** 3
GB = 1000 ** 3

# List prices in USD for a Firestore Standard database in nam5 and the default
# Cloud Storage bucket, with Blaze-plan free usage. Check
# https://firebase.google.com/pricing if Google changes them.
PRICES = {
    'reads_per_100k': 0.06,
    'writes_per_100k': 0.18,
    'deletes_per_100k': 0.02,
    'firestore_storage_per_gib_month': 0.18,
    'functions_per_million': 0.40,
    'storage_per_gb_month': 0.026,
    'egress_per_gb': 0.12,
}
FREE = {
    'reads_per_day': 50_000,
    'writes_per_day': 20_000,
    'deletes_per_day': 20_000,
    'firestore_storage_gib': 1,
    'functions_per_month': 2_000_000,
    'storage_gb': 5,
    'egress_gb_per_month': 100,
}

# key -> (metric type, per-hour aligner). Counts are summed per day;
# storage sizes keep the latest value of the day.
METRICS = {
    'reads': ('firestore.googleapis.com/document/read_count', 'ALIGN_SUM'),
    'writes': ('firestore.googleapis.com/document/write_count', 'ALIGN_SUM'),
    'deletes': ('firestore.googleapis.com/document/delete_count', 'ALIGN_SUM'),
    'firestore_bytes': ('firestore.googleapis.com/storage/data_and_index_storage_bytes', 'ALIGN_MAX'),
    'functions': ('cloudfunctions.googleapis.com/function/execution_count', 'ALIGN_SUM'),
    'storage_bytes': ('storage.googleapis.com/storage/total_bytes', 'ALIGN_MAX'),
    'egress_bytes': ('storage.googleapis.com/network/sent_bytes_count', 'ALIGN_SUM'),
}
GAUGES = {'firestore_bytes', 'storage_bytes'}


class UsageUnavailable(Exception):
    """Usage or billing data could not be loaded; message is safe to show."""


def usd_to_inr() -> float:
    try:
        return float(os.getenv('USD_TO_INR_RATE') or getattr(settings, 'USD_TO_INR_RATE', 0) or 88.0)
    except (TypeError, ValueError):
        return 88.0


def _credentials():
    from google.oauth2 import service_account

    scopes = ['https://www.googleapis.com/auth/cloud-platform']
    raw = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
    path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    if path:
        return service_account.Credentials.from_service_account_file(path, scopes=scopes)
    raise UsageUnavailable('Firebase credentials are not configured.')


def _project_id(creds) -> str:
    return getattr(settings, 'FIREBASE_PROJECT_ID', '') or getattr(creds, 'project_id', '') or ''


def _point_value(point) -> float:
    value = point.get('value', {})
    for key in ('int64Value', 'doubleValue'):
        if key in value:
            return float(value[key])
    return 0.0


def bucket_by_day(points, gauge: bool, tz=PACIFIC) -> dict[dt.date, float]:
    """Hourly points [(end_time_iso, value)] -> {pacific_date: daily value}."""
    out: dict[dt.date, float] = defaultdict(float)
    latest: dict[dt.date, tuple[dt.datetime, float]] = {}
    for end_time, value in points:
        when = dt.datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        # A point covers the hour that *ends* at end_time.
        day = (when - dt.timedelta(seconds=1)).astimezone(tz).date()
        if gauge:
            if day not in latest or when > latest[day][0]:
                latest[day] = (when, value)
        else:
            out[day] += value
    if gauge:
        return {day: v for day, (_, v) in latest.items()}
    return dict(out)


def fetch_daily_usage(days: int = 31, now: dt.datetime | None = None) -> dict:
    """Daily usage per metric for the last `days` Pacific days (today included)."""
    from googleapiclient.discovery import build

    creds = _credentials()
    project = _project_id(creds)
    if not project:
        raise UsageUnavailable('Could not tell which Firebase project to read.')
    mon = build('monitoring', 'v3', credentials=creds, cache_discovery=False)

    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(PACIFIC).date()
    first_day = today - dt.timedelta(days=days - 1)
    start = PACIFIC.localize(dt.datetime.combine(first_day, dt.time())).astimezone(dt.timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)

    series: dict[str, dict[dt.date, float]] = {}
    for key, (metric, aligner) in METRICS.items():
        points = []
        page_token = None
        while True:
            try:
                resp = mon.projects().timeSeries().list(
                    name=f'projects/{project}',
                    filter=f'metric.type="{metric}"',
                    interval_startTime=start.isoformat(),
                    interval_endTime=end.isoformat(),
                    aggregation_alignmentPeriod='3600s',
                    aggregation_perSeriesAligner=aligner,
                    aggregation_crossSeriesReducer='REDUCE_SUM',
                    pageToken=page_token,
                ).execute()
            except Exception as exc:
                logger.exception('Monitoring query failed for %s', metric)
                raise UsageUnavailable(
                    'Could not read usage from Google Cloud Monitoring. '
                    'Check that the service account has the Monitoring Viewer role.'
                ) from exc
            for ts in resp.get('timeSeries', []):
                for p in ts.get('points', []):
                    points.append((p['interval']['endTime'], _point_value(p)))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        series[key] = bucket_by_day(points, gauge=key in GAUGES)

    day_list = [first_day + dt.timedelta(days=i) for i in range(days)]
    return {'project': project, 'today': today, 'days': day_list, 'series': series}


def _over(value: float, free: float) -> float:
    return max(0.0, value - free)


def day_cost(row: dict) -> dict:
    """Estimated USD for one day's Firestore operations (daily free quota)."""
    reads = _over(row.get('reads', 0), FREE['reads_per_day']) / 100_000 * PRICES['reads_per_100k']
    writes = _over(row.get('writes', 0), FREE['writes_per_day']) / 100_000 * PRICES['writes_per_100k']
    deletes = _over(row.get('deletes', 0), FREE['deletes_per_day']) / 100_000 * PRICES['deletes_per_100k']
    return {'reads': reads, 'writes': writes, 'deletes': deletes, 'total': reads + writes + deletes}


def month_estimate(rows: list[dict], days_in_month: int) -> dict:
    """Estimated USD for the month so far from this month's daily rows."""
    ops = [day_cost(r) for r in rows]
    elapsed = len(rows) or 1
    fs_gib = [r.get('firestore_bytes', 0) / GIB for r in rows if r.get('firestore_bytes')]
    st_gb = [r.get('storage_bytes', 0) / GB for r in rows if r.get('storage_bytes')]
    avg_fs = sum(fs_gib) / len(fs_gib) if fs_gib else 0.0
    avg_st = sum(st_gb) / len(st_gb) if st_gb else 0.0
    month_share = elapsed / days_in_month

    functions_calls = sum(r.get('functions', 0) for r in rows)
    egress_gb = sum(r.get('egress_bytes', 0) for r in rows) / GB

    parts = {
        'Firestore reads': sum(o['reads'] for o in ops),
        'Firestore writes': sum(o['writes'] for o in ops),
        'Firestore deletes': sum(o['deletes'] for o in ops),
        'Firestore storage': _over(avg_fs, FREE['firestore_storage_gib'])
        * PRICES['firestore_storage_per_gib_month'] * month_share,
        'Cloud Functions calls': _over(functions_calls, FREE['functions_per_month'])
        / 1_000_000 * PRICES['functions_per_million'],
        'Cloud Storage': _over(avg_st, FREE['storage_gb']) * PRICES['storage_per_gb_month'] * month_share,
        'Cloud Storage downloads': _over(egress_gb, FREE['egress_gb_per_month']) * PRICES['egress_per_gb'],
    }
    return {'parts': parts, 'total': sum(parts.values())}


def _round_rows(usage: dict) -> list[dict]:
    rows = []
    for day in usage['days']:
        row = {'date': day}
        for key in METRICS:
            row[key] = usage['series'].get(key, {}).get(day, 0.0)
        rows.append(row)
    return rows


def _pct(value: float, limit: float) -> int:
    return int(min(100, round(value / limit * 100))) if limit else 0


def build_summary(usage: dict) -> dict:
    """Everything the page shows, from fetch_daily_usage() output."""
    rate = usd_to_inr()
    rows = _round_rows(usage)
    today = usage['today']
    today_row = rows[-1] if rows else {'date': today}
    month_rows = [r for r in rows if r['date'].year == today.year and r['date'].month == today.month]
    next_month = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - today.replace(day=1)).days

    estimate = month_estimate(month_rows, days_in_month)
    elapsed = len(month_rows) or 1
    projected = estimate['total'] / elapsed * days_in_month

    for r in rows:
        r['cost_usd'] = day_cost(r)['total']
        r['cost_inr'] = r['cost_usd'] * rate
        r['firestore_mb'] = r['firestore_bytes'] / 1024 ** 2

    def last_gauge(key):
        for r in reversed(rows):
            if r.get(key):
                return r[key]
        return 0.0

    firestore_gib = last_gauge('firestore_bytes') / GIB
    storage_gb = last_gauge('storage_bytes') / GB
    functions_month = sum(r['functions'] for r in month_rows)
    egress_month_gb = sum(r['egress_bytes'] for r in month_rows) / GB

    quotas = [
        {'label': 'Reads today', 'used': today_row.get('reads', 0), 'limit': FREE['reads_per_day'], 'unit': ''},
        {'label': 'Writes today', 'used': today_row.get('writes', 0), 'limit': FREE['writes_per_day'], 'unit': ''},
        {'label': 'Deletes today', 'used': today_row.get('deletes', 0), 'limit': FREE['deletes_per_day'], 'unit': ''},
        {'label': 'Firestore storage', 'used': firestore_gib, 'limit': FREE['firestore_storage_gib'], 'unit': 'GiB'},
        {'label': 'Function calls this month', 'used': functions_month, 'limit': FREE['functions_per_month'], 'unit': ''},
        {'label': 'Cloud Storage size', 'used': storage_gb, 'limit': FREE['storage_gb'], 'unit': 'GB'},
        {'label': 'Downloads this month', 'used': egress_month_gb, 'limit': FREE['egress_gb_per_month'], 'unit': 'GB'},
    ]
    for q in quotas:
        q['pct'] = _pct(q['used'], q['limit'])

    return {
        'project': usage['project'],
        'today': today,
        'rate': rate,
        'today_row': today_row,
        'quotas': quotas,
        'month_label': today.strftime('%B %Y'),
        'month_parts': [
            {'label': k, 'usd': v, 'inr': v * rate} for k, v in estimate['parts'].items()
        ],
        'month_usd': estimate['total'],
        'month_inr': estimate['total'] * rate,
        'projected_usd': projected,
        'projected_inr': projected * rate,
        'rows': list(reversed(rows)),
        'chart': {
            'labels': [r['date'].strftime('%d %b') for r in rows],
            'reads': [int(r['reads']) for r in rows],
            'writes': [int(r['writes']) for r in rows],
            'deletes': [int(r['deletes']) for r in rows],
            'functions': [int(r['functions']) for r in rows],
        },
        'prices': PRICES,
        'free': FREE,
    }


def get_usage_summary(refresh: bool = False) -> dict:
    key = 'firebase_usage_summary_v1'
    if not refresh:
        cached = cache.get(key)
        if cached:
            return cached
    summary = build_summary(fetch_daily_usage())
    summary['loaded_at'] = dt.datetime.now(dt.timezone.utc)
    cache.set(key, summary, CACHE_SECONDS)
    return summary


# ---- Exact bill from the BigQuery billing export ---------------------------

_TABLE_RE = re.compile(r'^[a-z][a-z0-9-]{4,61}[a-z0-9]\.[A-Za-z0-9_]{1,1024}\.[A-Za-z0-9_$-]{1,1024}$')


def billing_table() -> str:
    return (os.getenv('FIREBASE_BILLING_EXPORT_TABLE') or getattr(settings, 'FIREBASE_BILLING_EXPORT_TABLE', '') or '').strip()


def fetch_billing(table: str, project: str, months: int = 3) -> dict:
    """Actual cost per service for recent invoice months from the billing export."""
    from googleapiclient.discovery import build

    if not _TABLE_RE.match(table):
        raise UsageUnavailable('FIREBASE_BILLING_EXPORT_TABLE must look like project.dataset.table.')
    creds = _credentials()
    job_project = table.split('.', 1)[0]
    bq = build('bigquery', 'v2', credentials=creds, cache_discovery=False)
    query = f"""
        SELECT invoice.month AS month,
               service.description AS service,
               currency,
               SUM(cost) AS cost,
               SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits
        FROM `{table}`
        WHERE project.id = @project
          AND invoice.month >= FORMAT_DATE('%Y%m', DATE_SUB(CURRENT_DATE(), INTERVAL @months MONTH))
        GROUP BY month, service, currency
        ORDER BY month DESC, cost DESC
    """
    body = {
        'query': query,
        'useLegacySql': False,
        'timeoutMs': 30000,
        'parameterMode': 'NAMED',
        'queryParameters': [
            {'name': 'project', 'parameterType': {'type': 'STRING'}, 'parameterValue': {'value': project}},
            {'name': 'months', 'parameterType': {'type': 'INT64'}, 'parameterValue': {'value': str(months - 1)}},
        ],
    }
    try:
        resp = bq.jobs().query(projectId=job_project, body=body).execute()
    except Exception as exc:
        logger.exception('Billing export query failed')
        raise UsageUnavailable(
            'Could not read the billing export from BigQuery. Check the table name and that the '
            'service account has BigQuery Job User and BigQuery Data Viewer.'
        ) from exc
    if not resp.get('jobComplete', True):
        raise UsageUnavailable('The billing query took too long. Reload the page to try again.')

    fields = [f['name'] for f in resp.get('schema', {}).get('fields', [])]
    months_out: dict[str, dict] = {}
    for row in resp.get('rows', []):
        rec = dict(zip(fields, [c.get('v') for c in row['f']]))
        month = rec['month'] or ''
        net = float(rec['cost'] or 0) + float(rec['credits'] or 0)
        entry = months_out.setdefault(month, {
            'month': month,
            'label': dt.datetime.strptime(month, '%Y%m').strftime('%B %Y') if len(month) == 6 else month,
            'currency': rec['currency'] or '',
            'services': [],
            'total': 0.0,
        })
        entry['services'].append({
            'service': rec['service'] or 'Other',
            'cost': float(rec['cost'] or 0),
            'credits': float(rec['credits'] or 0),
            'net': net,
        })
        entry['total'] += net
    return {'months': sorted(months_out.values(), key=lambda m: m['month'], reverse=True)}


def get_billing(project: str, refresh: bool = False) -> dict | None:
    """None when the billing export is not configured."""
    table = billing_table()
    if not table:
        return None
    key = 'firebase_billing_v1'
    if not refresh:
        cached = cache.get(key)
        if cached:
            return cached
    data = fetch_billing(table, project)
    cache.set(key, data, CACHE_SECONDS)
    return data
