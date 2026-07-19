"""
Referral read / analytics helpers for the Admin Dashboard.

Mirrors the Flutter + Cloud Functions schema in the sudo mobile project:
  - referrals/{referredUserId}
  - referralCodes/{CODE}
  - users/{uid}.referralCode / referredBy* / referralStats

Writes to referrals / referralStats are owned by Cloud Functions — this module is
read-only (plus CSV export of query results).
"""
from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from io import StringIO
from typing import Any, Iterable, Optional

import pytz
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

REFERRAL_STATUS = {
    'PENDING': 'pending',
    'SUCCESSFUL': 'successful',
    'REWARDED': 'rewarded',
}

REWARD_STATUS = {
    'NONE': 'none',
    'PENDING': 'pending',
    'GRANTED': 'granted',
}

SUCCESS_STATUSES = frozenset({
    REFERRAL_STATUS['SUCCESSFUL'],
    REFERRAL_STATUS['REWARDED'],
})

REFERRAL_LINK_TEMPLATE = 'https://sudotag.com/r/{code}'

# Cap streams so overview/export never pull unbounded collections into memory.
DEFAULT_FETCH_LIMIT = 2000
EXPORT_ROW_CAP = 5000
TOP_REFERRERS_LIMIT = 15
RECENT_LIMIT = 15


def _get_db():
    from .views import db
    return db


def empty_referral_stats() -> dict[str, Any]:
    return {
        'totalReferrals': 0,
        'successfulReferrals': 0,
        'pendingReferrals': 0,
        'rewardsEarned': 0,
    }


def normalize_referral_code(code: Optional[str]) -> str:
    if not code:
        return ''
    return ''.join(ch for ch in str(code).strip().upper() if ch.isalnum())


def referral_link_for(code: str) -> str:
    return REFERRAL_LINK_TEMPLATE.format(code=normalize_referral_code(code))


def qr_png_data_uri(payload: str, *, box_size: int = 8, border: int = 2) -> str:
    """PNG data-URI for a scannable QR (used on public invite / How It Works)."""
    import base64
    import io

    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#111111', back_color='#FFFFFF')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def _to_datetime(value: Any) -> Optional[datetime]:
    """Normalize Firestore Timestamp / datetime / string → aware datetime (UTC)."""
    if value is None:
        return None
    if hasattr(value, 'to_datetime'):
        try:
            dt = value.to_datetime()
            if dt.tzinfo is None:
                return pytz.UTC.localize(dt)
            return dt
        except Exception:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return pytz.UTC.localize(value)
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return IST.localize(datetime.combine(value, time.min))
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            pass
    return None


def _to_ist(value: Any) -> Optional[datetime]:
    dt = _to_datetime(value)
    if not dt:
        return None
    return dt.astimezone(IST)


def parse_date_param(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def map_referral_doc(doc_id: str, data: Optional[dict]) -> dict[str, Any]:
    """Mirror ReferralModel.fromFirestore — exact field names from mobile."""
    data = data or {}
    registered_at = _to_datetime(data.get('registeredAt'))
    created_at = _to_datetime(data.get('createdAt'))
    updated_at = _to_datetime(data.get('updatedAt'))
    status = (data.get('status') or REFERRAL_STATUS['PENDING']).strip()
    reward_status = data.get('rewardStatus')
    if reward_status is not None:
        reward_status = str(reward_status)
    reward_amount = data.get('rewardAmount')
    try:
        reward_amount = float(reward_amount) if reward_amount is not None else 0.0
    except (TypeError, ValueError):
        reward_amount = 0.0

    return {
        'id': doc_id,
        'referrerUserId': data.get('referrerUserId') or '',
        'referrerName': data.get('referrerName') or '',
        'referrerContact': data.get('referrerContact') or '',
        'referralCode': data.get('referralCode') or '',
        'referredUserId': data.get('referredUserId') or doc_id,
        'referredUserName': data.get('referredUserName') or '',
        'referredContact': data.get('referredContact') or '',
        'registeredAt': registered_at,
        'registeredAtIst': _to_ist(registered_at),
        'status': status,
        'rewardStatus': reward_status if reward_status is not None else REWARD_STATUS['NONE'],
        'rewardAmount': reward_amount,
        'createdAt': created_at,
        'updatedAt': updated_at,
        'isSuccessful': status in SUCCESS_STATUSES,
        'isPending': status == REFERRAL_STATUS['PENDING'],
        'referralLink': referral_link_for(data.get('referralCode') or ''),
    }


def map_referral_stats(raw: Any) -> dict[str, Any]:
    stats = empty_referral_stats()
    if not isinstance(raw, dict):
        return stats
    for key in stats:
        try:
            val = raw.get(key, 0)
            stats[key] = int(val) if key != 'rewardsEarned' else float(val or 0)
        except (TypeError, ValueError):
            pass
    return stats


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start = IST.localize(datetime.combine(day, time.min))
    end = IST.localize(datetime.combine(day, time.max))
    return start.astimezone(pytz.UTC), end.astimezone(pytz.UTC)


def _range_bounds_utc(start_day: Optional[date], end_day: Optional[date]) -> tuple[Optional[datetime], Optional[datetime]]:
    start_dt = end_dt = None
    if start_day:
        start_dt, _ = _day_bounds_utc(start_day)
    if end_day:
        _, end_dt = _day_bounds_utc(end_day)
    return start_dt, end_dt


def fetch_referrals(
    *,
    status: Optional[str] = None,
    reward_status: Optional[str] = None,
    referrer_user_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search: Optional[str] = None,
    limit: int = DEFAULT_FETCH_LIMIT,
) -> list[dict[str, Any]]:
    """
    Load referrals with server-side status/date/referrer filters where indexes allow,
    then optional client-side search + rewardStatus filter.
    Ordered by registeredAt descending.
    """
    db = _get_db()
    query = db.collection('referrals')

    if referrer_user_id:
        query = query.where(filter=FieldFilter('referrerUserId', '==', referrer_user_id))

    if status and status in (
        REFERRAL_STATUS['PENDING'],
        REFERRAL_STATUS['SUCCESSFUL'],
        REFERRAL_STATUS['REWARDED'],
    ):
        query = query.where(filter=FieldFilter('status', '==', status))

    start_dt, end_dt = _range_bounds_utc(start_date, end_date)
    if start_dt:
        query = query.where(filter=FieldFilter('registeredAt', '>=', start_dt))
    if end_dt:
        query = query.where(filter=FieldFilter('registeredAt', '<=', end_dt))

    try:
        query = query.order_by('registeredAt', direction=firestore.Query.DESCENDING)
        docs = list(query.limit(limit).stream())
    except Exception as exc:
        logger.warning('Referral ordered query failed (%s); falling back to unordered stream', exc)
        try:
            docs = list(db.collection('referrals').limit(limit).stream())
        except Exception as exc2:
            logger.exception('Referral fetch failed: %s', exc2)
            return []

    rows = [map_referral_doc(doc.id, doc.to_dict()) for doc in docs]

    # Fallback sort if unordered path was used
    rows.sort(
        key=lambda r: r.get('registeredAt') or datetime.min.replace(tzinfo=pytz.UTC),
        reverse=True,
    )

    if reward_status and reward_status in REWARD_STATUS.values():
        rows = [r for r in rows if (r.get('rewardStatus') or REWARD_STATUS['NONE']) == reward_status]

    if search:
        needle = search.strip().lower()
        if needle:
            def _matches(r: dict) -> bool:
                hay = ' '.join([
                    str(r.get('referrerName') or ''),
                    str(r.get('referrerContact') or ''),
                    str(r.get('referralCode') or ''),
                    str(r.get('referredUserName') or ''),
                    str(r.get('referredContact') or ''),
                    str(r.get('referrerUserId') or ''),
                    str(r.get('referredUserId') or ''),
                ]).lower()
                return needle in hay
            rows = [r for r in rows if _matches(r)]

    return rows


def get_referral_by_id(referral_id: str) -> Optional[dict[str, Any]]:
    if not referral_id:
        return None
    db = _get_db()
    doc = db.collection('referrals').document(referral_id).get()
    if not doc.exists:
        return None
    return map_referral_doc(doc.id, doc.to_dict())


def get_user_referral_profile(user_id: str) -> Optional[dict[str, Any]]:
    if not user_id:
        return None
    db = _get_db()
    doc = db.collection('users').document(user_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    code = data.get('referralCode') or ''
    return {
        'id': doc.id,
        'fullName': data.get('fullName') or '',
        'contactNumber': data.get('contactNumber') or '',
        'emailAddress': data.get('emailAddress') or '',
        'referralCode': code,
        'referredByCode': data.get('referredByCode'),
        'referredByUserId': data.get('referredByUserId'),
        'referralStats': map_referral_stats(data.get('referralStats')),
        'referralLink': referral_link_for(code) if code else '',
    }


def lookup_referral_code(code: str) -> Optional[dict[str, Any]]:
    normalized = normalize_referral_code(code)
    if not normalized:
        return None
    db = _get_db()
    doc = db.collection('referralCodes').document(normalized).get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return {
        'code': doc.id,
        'userId': data.get('userId') or '',
        'userName': data.get('userName') or '',
        'contactNumber': data.get('contactNumber') or '',
        'createdAt': _to_datetime(data.get('createdAt')),
        'isActive': bool(data.get('isActive', True)),
        'referralLink': referral_link_for(doc.id),
    }


def compute_kpis(referrals: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(referrals)
    total = len(rows)
    pending = sum(1 for r in rows if r.get('status') == REFERRAL_STATUS['PENDING'])
    successful = sum(1 for r in rows if r.get('status') == REFERRAL_STATUS['SUCCESSFUL'])
    rewarded = sum(1 for r in rows if r.get('status') == REFERRAL_STATUS['REWARDED'])
    # Mobile treats successful + rewarded as success for conversion.
    converted = successful + rewarded
    conversion_rate = round((converted / total) * 100, 1) if total else 0.0
    return {
        'total': total,
        'pending': pending,
        'successful': successful,
        'rewarded': rewarded,
        'converted': converted,
        'conversion_rate': conversion_rate,
    }


def build_time_series(referrals: list[dict[str, Any]], *, days: int = 30) -> dict[str, Any]:
    """Daily / weekly / monthly volume buckets from registeredAt (IST)."""
    today = datetime.now(IST).date()
    daily_start = today - timedelta(days=max(days - 1, 0))

    daily_counts: dict[str, int] = {}
    for i in range(days):
        d = daily_start + timedelta(days=i)
        daily_counts[d.isoformat()] = 0

    weekly_counts: dict[str, int] = defaultdict(int)
    monthly_counts: dict[str, int] = defaultdict(int)
    status_counts = Counter()

    for row in referrals:
        status_counts[row.get('status') or 'unknown'] += 1
        reg = row.get('registeredAtIst') or _to_ist(row.get('registeredAt'))
        if not reg:
            continue
        d = reg.date()
        key = d.isoformat()
        if key in daily_counts:
            daily_counts[key] += 1
        iso = d.isocalendar()
        weekly_counts[f'{iso.year}-W{iso.week:02d}'] += 1
        monthly_counts[f'{d.year}-{d.month:02d}'] += 1

    # Keep last 12 weeks / 12 months for chart readability
    weekly_keys = sorted(weekly_counts.keys())[-12:]
    monthly_keys = sorted(monthly_counts.keys())[-12:]

    return {
        'daily_labels': list(daily_counts.keys()),
        'daily_values': list(daily_counts.values()),
        'weekly_labels': weekly_keys,
        'weekly_values': [weekly_counts[k] for k in weekly_keys],
        'monthly_labels': monthly_keys,
        'monthly_values': [monthly_counts[k] for k in monthly_keys],
        'status_labels': [
            REFERRAL_STATUS['PENDING'],
            REFERRAL_STATUS['SUCCESSFUL'],
            REFERRAL_STATUS['REWARDED'],
        ],
        'status_values': [
            status_counts.get(REFERRAL_STATUS['PENDING'], 0),
            status_counts.get(REFERRAL_STATUS['SUCCESSFUL'], 0),
            status_counts.get(REFERRAL_STATUS['REWARDED'], 0),
        ],
    }


def top_referrers_from_users(*, limit: int = TOP_REFERRERS_LIMIT) -> list[dict[str, Any]]:
    """
    Rank users by referralStats.successfulReferrals then totalReferrals.
    Streams a bounded sample of users that have referralCode / referralStats.
    """
    db = _get_db()
    ranked: list[dict[str, Any]] = []
    try:
        # Prefer users who already have a referral code assigned by CF.
        docs = list(db.collection('users').limit(1500).stream())
    except Exception as exc:
        logger.exception('Failed loading users for top referrers: %s', exc)
        return []

    for doc in docs:
        data = doc.to_dict() or {}
        stats = map_referral_stats(data.get('referralStats'))
        if stats['totalReferrals'] <= 0 and not data.get('referralCode'):
            continue
        if stats['totalReferrals'] <= 0:
            continue
        ranked.append({
            'userId': doc.id,
            'fullName': data.get('fullName') or '',
            'contactNumber': data.get('contactNumber') or '',
            'referralCode': data.get('referralCode') or '',
            'referralLink': referral_link_for(data.get('referralCode') or ''),
            'stats': stats,
        })

    ranked.sort(
        key=lambda u: (
            u['stats']['successfulReferrals'],
            u['stats']['totalReferrals'],
            u['stats']['rewardsEarned'],
        ),
        reverse=True,
    )
    return ranked[:limit]


def top_referrers_from_edges(referrals: list[dict[str, Any]], *, limit: int = TOP_REFERRERS_LIMIT) -> list[dict[str, Any]]:
    """Fallback ranking from referral edges when user.stats are sparse."""
    by_referrer: dict[str, dict[str, Any]] = {}
    for row in referrals:
        uid = row.get('referrerUserId') or ''
        if not uid:
            continue
        bucket = by_referrer.setdefault(uid, {
            'userId': uid,
            'fullName': row.get('referrerName') or '',
            'contactNumber': row.get('referrerContact') or '',
            'referralCode': row.get('referralCode') or '',
            'referralLink': referral_link_for(row.get('referralCode') or ''),
            'stats': empty_referral_stats(),
        })
        bucket['stats']['totalReferrals'] += 1
        if row.get('status') == REFERRAL_STATUS['PENDING']:
            bucket['stats']['pendingReferrals'] += 1
        elif row.get('status') in SUCCESS_STATUSES:
            bucket['stats']['successfulReferrals'] += 1
        if not bucket['fullName'] and row.get('referrerName'):
            bucket['fullName'] = row['referrerName']

    ranked = list(by_referrer.values())
    ranked.sort(
        key=lambda u: (u['stats']['successfulReferrals'], u['stats']['totalReferrals']),
        reverse=True,
    )
    return ranked[:limit]


def build_overview(*, analytics_days: int = 30) -> dict[str, Any]:
    referrals = fetch_referrals(limit=DEFAULT_FETCH_LIMIT)
    kpis = compute_kpis(referrals)
    series = build_time_series(referrals, days=analytics_days)
    top = top_referrers_from_users(limit=TOP_REFERRERS_LIMIT)
    if not top:
        top = top_referrers_from_edges(referrals, limit=TOP_REFERRERS_LIMIT)
    recent = referrals[:RECENT_LIMIT]
    truncated = len(referrals) >= DEFAULT_FETCH_LIMIT
    return {
        'kpis': kpis,
        'series': series,
        'top_referrers': top,
        'recent_referrals': recent,
        'truncated': truncated,
        'fetch_limit': DEFAULT_FETCH_LIMIT,
        'conversion_note': (
            'Conversion rate = (successful + rewarded) / total × 100, '
            'matching mobile isSuccessful semantics.'
        ),
    }


def referrals_to_csv_rows(referrals: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    headers = [
        'Referrer Name',
        'Referrer Mobile',
        'Referral Code',
        'Referred User Name',
        'Referred User Mobile',
        'Registration Date (IST)',
        'Referral Status',
        'Reward Status',
        'Reward Amount',
        'Referrer User ID',
        'Referred User ID',
    ]
    rows = []
    for r in referrals:
        reg = r.get('registeredAtIst') or _to_ist(r.get('registeredAt'))
        rows.append([
            r.get('referrerName') or '',
            r.get('referrerContact') or '',
            r.get('referralCode') or '',
            r.get('referredUserName') or '',
            r.get('referredContact') or '',
            reg.strftime('%Y-%m-%d %H:%M:%S') if reg else '',
            r.get('status') or '',
            r.get('rewardStatus') or '',
            r.get('rewardAmount') or 0,
            r.get('referrerUserId') or '',
            r.get('referredUserId') or '',
        ])
    return headers, rows


def export_referrals_csv(
    referrals: list[dict[str, Any]],
    *,
    filename: str = 'referrals_export.csv',
) -> tuple[str, str, bool]:
    """
    Returns (csv_text, filename, truncated).
    Caps at EXPORT_ROW_CAP rows.
    """
    truncated = len(referrals) > EXPORT_ROW_CAP
    capped = referrals[:EXPORT_ROW_CAP]
    headers, rows = referrals_to_csv_rows(capped)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue(), filename, truncated
