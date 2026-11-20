"""CivicSense admin: report review, awareness campaigns and Civic Points.

Mirrors `functions/civic_sense.js` in the mobile repo. The admin panel logs in
with a Django session, not a Firebase admin claim, so it cannot call the
`adminUpdateCivicReport` callable. It writes the same documents with the Admin
SDK instead, using the same rules:

- `civic_reports/{id}`          reporter-readable. Never holds owner data.
- `civic_reports_private/{id}`  admin-only owner match, push state, flags.
- `civic_owner_alerts/{id}`     owner-readable. Never holds reporter data.
- `civic_points/{uid}` + `ledger`, mirrored to `civic_leaderboard/{randomId}`.

Anything written to `civic_reports` (status, timeline note, resolutionNote) is
visible to the reporter. Never copy owner details into it.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from django.core.cache import cache
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)

REPORTS = 'civic_reports'
PRIVATE = 'civic_reports_private'
ALERTS = 'civic_owner_alerts'
ACTIONS_LOG = 'civic_report_actions'
ADMIN_LOGS = 'civic_admin_logs'
AWARENESS = 'civic_awareness'
STATS = 'civic_stats'
STATS_DOC = 'global'
POINTS_COLL = 'civic_points'
LEADERBOARD = 'civic_leaderboard'
RATE_LIMITS = 'civic_rate_limits'

LIST_LIMIT = 500
OPEN_COUNT_CACHE_KEY = 'civic_reports_open_count'

MAX_ADMIN_NOTE = 500
MAX_ADJUST_REASON = 200
MAX_ADJUST_POINTS = 500
EVIDENCE_AFTER_CLOSE = timedelta(days=7)

STATUSES = ('submitted', 'under_review', 'verified', 'resolved', 'rejected', 'duplicate', 'withdrawn')
TERMINAL = {'resolved', 'rejected', 'duplicate', 'withdrawn'}
OPEN_STATUSES = ('submitted', 'under_review')

# from -> allowed targets. Same table as ADMIN_TRANSITIONS in civic_sense.js.
ADMIN_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    'submitted': ('under_review', 'verified', 'resolved', 'rejected', 'duplicate'),
    'under_review': ('verified', 'resolved', 'rejected', 'duplicate'),
    'verified': ('resolved', 'rejected', 'duplicate'),
    'resolved': ('under_review',),
    'rejected': ('under_review',),
    'duplicate': ('under_review',),
    'withdrawn': (),
}

STATUS_LABELS = {
    'submitted': 'Submitted',
    'under_review': 'Under review',
    'verified': 'Verified',
    'resolved': 'Resolved',
    'rejected': 'Not accepted',
    'duplicate': 'Duplicate',
    'withdrawn': 'Withdrawn',
}

# Button wording for each target status.
ACTION_LABELS = {
    'under_review': ('Mark under review', 'fa-search', 'btn-outline-secondary'),
    'verified': ('Verify report', 'fa-check', 'btn-success'),
    'resolved': ('Mark resolved', 'fa-check-double', 'btn-success'),
    'rejected': ('Reject (not accepted)', 'fa-ban', 'btn-danger'),
    'duplicate': ('Mark duplicate', 'fa-clone', 'btn-outline-danger'),
}

CATEGORY_LABELS = {
    'wrong_parking': 'Wrong parking',
    'road_obstruction': 'Road obstruction',
    'footpath_blocking': 'Footpath blocked',
    'emergency_access': 'Emergency access blocked',
    'driveway_blocking': 'Driveway or gate blocked',
    'abandoned_vehicle': 'Abandoned vehicle',
    'other': 'Other vehicle issue',
}

MATCH_LABELS = {
    'matched': 'Matched a SudoTag vehicle',
    'none': 'No SudoTag vehicle with this plate',
    'ambiguous': 'More than one vehicle has this plate',
    'no_plate': 'No plate given',
    'self': 'Reporter owns this vehicle',
}

NOTIFY_LABELS = {
    'sent': 'Push sent',
    'failed': 'Push failed',
    'skipped_pref': 'Not sent: owner turned off push',
    'skipped_no_token': 'Not sent: owner has no device',
    'skipped_rate': 'Not sent: vehicle push limit reached',
    'skipped_abuse': 'Not sent: reporter flagged for repeat reports',
    'not_applicable': 'Not applicable',
}

OWNER_STATUS_LABELS = {
    'new': 'New',
    'acknowledged': 'Acknowledged',
    'resolved': 'Resolved',
    'disputed': 'Disputed',
}

AWARENESS_CATEGORIES = {
    'parking_tips': 'Parking tips',
    'road_safety': 'Road safety',
    'general': 'General',
}

# ─── Civic Points (same values as POINTS / LEVELS in civic_sense.js) ─────────
POINTS = {
    'report_verified': 5,
    'report_resolved': 10,
    'daily_cap': 30,
}

LEVELS = (
    (0, 'member', 'Community member'),
    (25, 'helper', 'Civic helper'),
    (100, 'champion', 'Civic champion'),
    (300, 'guardian', 'Road guardian'),
)
LEVEL_NAMES = {key: name for _, key, name in LEVELS}

LEDGER_LABELS = {
    'report_verified': 'Report verified',
    'report_resolved': 'Report resolved',
    'owner_response': 'Owner responded to an alert',
    'revoke_report_verified': 'Revoked: report not accepted',
    'revoke_report_resolved': 'Revoked: report not accepted',
    'admin_adjustment': 'Adjusted by admin',
}


class CivicAdminError(ValueError):
    """A problem the admin can fix; the message is shown as is."""


# ─── Small helpers ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if hasattr(value, 'to_datetime'):
        try:
            return value.to_datetime()
        except Exception:
            return None
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return None


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def clean_text(raw, max_len: int) -> Optional[str]:
    """Same as cleanText in civic_sense.js: strip control chars, collapse spaces."""
    if raw is None:
        return None
    s = ''.join(ch for ch in str(raw) if ch in '\t\n\r' or ord(ch) >= 32 and ord(ch) != 127)
    s = ' '.join(s.split())
    if not s:
        return None
    return s[:max_len].strip() if len(s) > max_len else s


def day_key(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime('%Y-%m-%d')


def month_key(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime('%Y-%m')


def level_for(total) -> Tuple[str, str]:
    level = LEVELS[0]
    for entry in LEVELS:
        if _int(total) >= entry[0]:
            level = entry
    return level[1], level[2]


def apply_points(state: Optional[Dict[str, Any]], points: int, now: datetime,
                 respect_cap: bool = True) -> Tuple[Dict[str, Any], int]:
    """Port of applyPoints(). Returns (next_fields, applied).

    `respect_cap=False` is only for manual admin adjustments, which are not
    earned and so do not count toward (or get blocked by) the daily cap.
    """
    s = state if isinstance(state, dict) else {}
    dk, mk = day_key(now), month_key(now)
    day_points = _int(s.get('dayPoints')) if s.get('dayKey') == dk else 0
    month_points = _int(s.get('monthPoints')) if s.get('monthKey') == mk else 0
    total = _int(s.get('total'))

    applied = points
    if points > 0 and respect_cap:
        applied = max(0, min(points, POINTS['daily_cap'] - day_points))
    if points < 0:
        applied = -min(-points, total)

    total += applied
    month_points = max(0, month_points + applied)
    earned_today = points > 0 and respect_cap
    return {
        'total': total,
        'monthKey': mk,
        'monthPoints': month_points,
        'dayKey': dk,
        'dayPoints': day_points + applied if earned_today else day_points,
        'level': level_for(total)[0],
    }, applied


def can_transition(current: str, target: str) -> bool:
    return target in ADMIN_TRANSITIONS.get(current, ())


def allowed_actions(current: str) -> List[Dict[str, str]]:
    out = []
    for target in ADMIN_TRANSITIONS.get(current, ()):
        label, icon, css = ACTION_LABELS[target]
        if current in ('resolved', 'rejected', 'duplicate') and target == 'under_review':
            label = 'Reopen for review'
        out.append({'status': target, 'label': label, 'icon': icon, 'css': css})
    return out


def _run_tx(db, fn: Callable):
    """Run fn(transaction) in a Firestore transaction (patched in tests)."""
    transaction = db.transaction()

    @firestore.transactional
    def _inner(tx):
        return fn(tx)

    return _inner(transaction)


def _get(ref, tx=None):
    return ref.get(transaction=tx) if tx is not None else ref.get()


# ─── Normalising documents for templates ────────────────────────────────────

def normalize_report(doc_id: str, data: Dict[str, Any], priv: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    priv = priv or {}
    loc = data.get('location') if isinstance(data.get('location'), dict) else {}
    status = str(data.get('status') or 'submitted')
    timeline = []
    for row in data.get('timeline') or []:
        if isinstance(row, dict):
            timeline.append({
                'status': str(row.get('status') or ''),
                'label': STATUS_LABELS.get(str(row.get('status') or ''), str(row.get('status') or '')),
                'at': _as_datetime(row.get('at')),
                'note': row.get('note') or '',
            })
    timeline.sort(key=lambda r: r['at'] or datetime.min.replace(tzinfo=timezone.utc))
    category = str(data.get('category') or 'other')
    lat, lng = loc.get('lat'), loc.get('lng')
    has_loc = isinstance(lat, (int, float)) and isinstance(lng, (int, float))
    return {
        'id': doc_id,
        'report_id': str(data.get('reportId') or doc_id),
        'reporter_uid': str(data.get('reporterUid') or ''),
        'category': category,
        'category_label': CATEGORY_LABELS.get(category, category.replace('_', ' ').capitalize()),
        'description': data.get('description') or '',
        'plate': data.get('vehicleNumber') or '',
        'plate_masked': data.get('vehicleNumberMasked') or '',
        'lat': lat if has_loc else None,
        'lng': lng if has_loc else None,
        'accuracy': loc.get('accuracyM'),
        'address': data.get('address') or '',
        'landmark': data.get('landmark') or '',
        'evidence': [str(p) for p in (data.get('evidencePaths') or []) if p],
        'evidence_deleted': data.get('evidenceDeleted') is True,
        'evidence_delete_after': _as_datetime(data.get('evidenceDeleteAfter')),
        'status': status,
        'status_label': STATUS_LABELS.get(status, status),
        'is_open': status in OPEN_STATUSES,
        'resolution_note': data.get('resolutionNote') or '',
        'dup_of': data.get('dupOf') or '',
        'reviewed_by': data.get('reviewedBy') or '',
        'timeline': timeline,
        'created_at': _as_datetime(data.get('createdAt')),
        'updated_at': _as_datetime(data.get('updatedAt')),
        # private (admin-only) side
        'match_status': priv.get('matchStatus') or '',
        'match_label': MATCH_LABELS.get(priv.get('matchStatus') or '', priv.get('matchStatus') or 'Unknown'),
        'owner_uid': priv.get('ownerUid') or '',
        'vehicle_id': priv.get('vehicleId') or '',
        'alert_id': priv.get('alertId') or '',
        'notify_status': priv.get('ownerNotificationStatus') or '',
        'notify_label': NOTIFY_LABELS.get(priv.get('ownerNotificationStatus') or '',
                                          priv.get('ownerNotificationStatus') or '-'),
        'owner_status': priv.get('ownerStatus') or '',
        'owner_status_label': OWNER_STATUS_LABELS.get(priv.get('ownerStatus') or '', ''),
        'abuse': priv.get('abuseSuspected') is True,
        'disputed': priv.get('disputed') is True,
        'dispute_reason': priv.get('disputeReason') or '',
    }


def report_flags(report: Dict[str, Any]) -> bool:
    return report['abuse'] or report['disputed']


# ─── Report list, counts, detail ────────────────────────────────────────────

FILTERS = ('open', 'disputed', 'flagged', 'verified', 'resolved', 'closed', 'all')


def _latest(db, collection: str, limit: int = LIST_LIMIT) -> List[Any]:
    try:
        return list(
            db.collection(collection)
            .order_by('createdAt', direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
    except Exception as exc:
        logger.warning('civic admin: ordered read of %s failed (%s), reading unordered', collection, exc)
        return list(db.collection(collection).limit(limit).stream())


def _matches_filter(report: Dict[str, Any], state: str) -> bool:
    if state == 'open':
        return report['is_open']
    if state == 'disputed':
        return report['disputed'] and report['status'] not in TERMINAL
    if state == 'flagged':
        return report['abuse']
    if state == 'verified':
        return report['status'] == 'verified'
    if state == 'resolved':
        return report['status'] == 'resolved'
    if state == 'closed':
        return report['status'] in ('rejected', 'duplicate', 'withdrawn')
    return True


def list_reports(db, state: str = 'open', query: str = '', category: str = '') -> Dict[str, Any]:
    report_snaps = _latest(db, REPORTS)
    private = {s.id: (s.to_dict() or {}) for s in _latest(db, PRIVATE)}
    reports = [normalize_report(s.id, s.to_dict() or {}, private.get(s.id)) for s in report_snaps]
    reports.sort(key=lambda r: r['created_at'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    counts = {key: sum(1 for r in reports if _matches_filter(r, key)) for key in FILTERS}
    counts['all'] = len(reports)

    rows = [r for r in reports if _matches_filter(r, state)]
    if category:
        rows = [r for r in rows if r['category'] == category]
    if state == 'open':
        # Oldest first so nothing waits too long; disputed and emergency first.
        rows.sort(key=lambda r: (
            not r['disputed'],
            r['category'] != 'emergency_access',
            r['created_at'] or datetime.min.replace(tzinfo=timezone.utc),
        ))
    needle = ''.join(query.split()).lower()
    if needle:
        rows = [
            r for r in rows
            if needle in ''.join([r['report_id'], r['id'], r['plate'], r['address'], r['landmark'],
                                  r['description'], r['reporter_uid'], r['owner_uid']]).replace(' ', '').lower()
        ]
    return {'reports': rows, 'counts': counts}


def open_report_count(db) -> int:
    """Reports waiting for an admin, for the sidebar badge (cached a minute)."""
    cached = cache.get(OPEN_COUNT_CACHE_KEY)
    if cached is not None:
        return cached
    count = 0
    try:
        for status in OPEN_STATUSES:
            q = db.collection(REPORTS).where(filter=FieldFilter('status', '==', status))
            try:
                result = q.count().get()
                count += int(result[0][0].value)
            except Exception:
                count += sum(1 for _ in q.stream())
    except Exception as exc:
        logger.warning('civic admin: open count failed: %s', exc)
    cache.set(OPEN_COUNT_CACHE_KEY, count, 60)
    return count


def get_users(db, uids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    users: Dict[str, Dict[str, str]] = {}
    for uid in {u for u in uids if u}:
        try:
            snap = db.collection('users').document(uid).get()
        except Exception:
            continue
        if not snap.exists:
            continue
        d = snap.to_dict() or {}
        users[uid] = {
            'name': str(d.get('fullName') or d.get('name') or d.get('displayName') or ''),
            'email': str(d.get('emailAddress') or d.get('email') or ''),
            'phone': str(d.get('contactNumber') or d.get('phoneNumber') or d.get('mobileNumber') or ''),
        }
    return users


def _log_rows(db, collection: str, doc_id: str) -> List[Dict[str, Any]]:
    rows = []
    try:
        for s in db.collection(collection).where(filter=FieldFilter('reportDocId', '==', doc_id)).stream():
            d = s.to_dict() or {}
            rows.append({**d, 'id': s.id, 'at': _as_datetime(d.get('at'))})
    except Exception as exc:
        logger.warning('civic admin: %s read failed: %s', collection, exc)
    rows.sort(key=lambda r: r['at'] or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def _ledger_for_report(db, uid: str, doc_id: str, reasons: Iterable[str]) -> List[Dict[str, Any]]:
    if not uid:
        return []
    rows = []
    ledger = db.collection(POINTS_COLL).document(uid).collection('ledger')
    for reason in reasons:
        snap = ledger.document(f'{doc_id}_{reason}').get()
        if snap.exists:
            d = snap.to_dict() or {}
            rows.append({
                'reason': reason,
                'label': LEDGER_LABELS.get(reason, reason),
                'points': _int(d.get('points')),
                'at': _as_datetime(d.get('at')),
            })
    return rows


def get_report_detail(db, doc_id: str) -> Optional[Dict[str, Any]]:
    snap = db.collection(REPORTS).document(doc_id).get()
    if not snap.exists:
        return None
    priv_snap = db.collection(PRIVATE).document(doc_id).get()
    report = normalize_report(doc_id, snap.to_dict() or {}, priv_snap.to_dict() if priv_snap.exists else {})

    alert = None
    if report['alert_id']:
        a = db.collection(ALERTS).document(report['alert_id']).get()
        if a.exists:
            ad = a.to_dict() or {}
            alert = {
                'id': a.id,
                'owner_status': ad.get('ownerStatus') or '',
                'owner_status_label': OWNER_STATUS_LABELS.get(ad.get('ownerStatus') or '', ad.get('ownerStatus') or ''),
                'closed_reason': ad.get('closedReason') or '',
                'dispute_reason': ad.get('disputeReason') or '',
                'description_safe': ad.get('descriptionSafe') or '',
                'reported_at': _as_datetime(ad.get('reportedAt')),
                'updated_at': _as_datetime(ad.get('updatedAt')),
            }

    vehicle = None
    if report['vehicle_id']:
        v = db.collection('vehicles').document(report['vehicle_id']).get()
        if v.exists:
            vd = v.to_dict() or {}
            vehicle = {
                'id': v.id,
                'number': vd.get('registrationNumber') or vd.get('vehicle_number') or '',
                'model': ' '.join(str(x) for x in (vd.get('brand') or vd.get('make'), vd.get('model')) if x),
            }

    activity = []
    for row in _log_rows(db, ACTIONS_LOG, doc_id):
        activity.append({
            'at': row['at'],
            'who': row.get('actorRole') or 'user',
            'action': row.get('action') or '',
            'note': row.get('note') or '',
        })
    for row in _log_rows(db, ADMIN_LOGS, doc_id):
        if row.get('action'):
            text = row.get('action')
        else:
            text = f"{STATUS_LABELS.get(row.get('from'), row.get('from'))} → {STATUS_LABELS.get(row.get('to'), row.get('to'))}"
        activity.append({
            'at': row['at'],
            'who': 'admin' + (f" ({row.get('adminEmail')})" if row.get('adminEmail') else ''),
            'action': text,
            'note': row.get('note') or '',
        })
    activity.sort(key=lambda r: r['at'] or datetime.min.replace(tzinfo=timezone.utc))

    if alert and not report['dispute_reason']:
        report['dispute_reason'] = alert['dispute_reason']
    users = get_users(db, [report['reporter_uid'], report['owner_uid']])
    return {
        'report': report,
        'alert': alert,
        'vehicle': vehicle,
        'activity': activity,
        'reporter': users.get(report['reporter_uid'], {}),
        'owner': users.get(report['owner_uid'], {}),
        'reporter_points': _ledger_for_report(
            db, report['reporter_uid'], doc_id,
            ('report_verified', 'report_resolved', 'revoke_report_verified', 'revoke_report_resolved')),
        'owner_points': _ledger_for_report(db, report['owner_uid'], doc_id, ('owner_response',)),
        'actions': allowed_actions(report['status']),
    }


# ─── Points writes (port of writePoints / awardPoints / revokeReportPoints) ─

def _write_points(db, tx, uid: str, prev: Dict[str, Any], nxt: Dict[str, Any],
                  show: Optional[bool] = None, public_name: Optional[str] = None) -> None:
    leaderboard_id = prev.get('leaderboardId') or secrets.token_hex(10)
    show_on = show if show is not None else prev.get('showOnLeaderboard') is True
    name = public_name if public_name is not None else (prev.get('publicName') or None)
    tx.set(db.collection(POINTS_COLL).document(uid), {
        **nxt,
        'leaderboardId': leaderboard_id,
        'showOnLeaderboard': show_on,
        'publicName': name if show_on else None,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)
    # Full overwrite, as in the function, so a hidden name never lingers.
    tx.set(db.collection(LEADERBOARD).document(leaderboard_id), {
        'monthKey': nxt['monthKey'],
        'monthPoints': nxt['monthPoints'],
        'total': nxt['total'],
        'level': nxt['level'],
        'publicName': name if show_on else None,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    })


def award_points(db, uid: str, doc_id: str, reason: str, points: int) -> int:
    """Idempotent: one ledger row per (user, report, reason). Never raises."""
    if not uid or not points:
        return 0
    points_ref = db.collection(POINTS_COLL).document(uid)
    ledger_ref = points_ref.collection('ledger').document(f'{doc_id}_{reason}')

    def fn(tx):
        ledger_snap, snap = _get(ledger_ref, tx), _get(points_ref, tx)
        if ledger_snap.exists:
            return 0
        prev = (snap.to_dict() or {}) if snap.exists else {}
        nxt, applied = apply_points(prev, points, _now())
        _write_points(db, tx, uid, prev, nxt)
        tx.set(ledger_ref, {
            'reason': reason,
            'reportDocId': doc_id,
            'points': applied,
            'requested': points,
            'at': firestore.SERVER_TIMESTAMP,
        })
        return applied

    try:
        return _run_tx(db, fn)
    except Exception as exc:
        logger.error('civic admin: points award failed (%s): %s', reason, exc)
        return 0


def revoke_report_points(db, uid: str, doc_id: str) -> None:
    if not uid:
        return
    points_ref = db.collection(POINTS_COLL).document(uid)
    for reason in ('report_verified', 'report_resolved'):
        earned_ref = points_ref.collection('ledger').document(f'{doc_id}_{reason}')
        revoke_ref = points_ref.collection('ledger').document(f'{doc_id}_revoke_{reason}')

        def fn(tx, earned_ref=earned_ref, revoke_ref=revoke_ref, reason=reason):
            earned, revoked, snap = _get(earned_ref, tx), _get(revoke_ref, tx), _get(points_ref, tx)
            amount = _int((earned.to_dict() or {}).get('points')) if earned.exists else 0
            if not amount or revoked.exists:
                return
            prev = (snap.to_dict() or {}) if snap.exists else {}
            nxt, applied = apply_points(prev, -amount, _now())
            _write_points(db, tx, uid, prev, nxt)
            tx.set(revoke_ref, {
                'reason': f'revoke_{reason}',
                'reportDocId': doc_id,
                'points': applied,
                'at': firestore.SERVER_TIMESTAMP,
            })

        try:
            _run_tx(db, fn)
        except Exception as exc:
            logger.error('civic admin: points revoke failed: %s', exc)


def _bump_stats(db, fields: Dict[str, int]) -> None:
    update: Dict[str, Any] = {'updatedAt': firestore.SERVER_TIMESTAMP}
    for key, value in fields.items():
        update[key] = firestore.Increment(value)
    try:
        db.collection(STATS).document(STATS_DOC).set(update, merge=True)
    except Exception as exc:
        logger.error('civic admin: stats update failed: %s', exc)


def _admin_log(db, doc_id: str, admin_email: str, note: Optional[str], **fields) -> None:
    try:
        db.collection(ADMIN_LOGS).add({
            'reportDocId': doc_id,
            'adminUid': None,
            'adminEmail': admin_email or 'admin',
            'source': 'admin_panel',
            'note': note or None,
            'at': firestore.SERVER_TIMESTAMP,
            **fields,
        })
    except Exception as exc:
        logger.error('civic admin: admin log failed: %s', exc)


def _invalidate():
    cache.delete(OPEN_COUNT_CACHE_KEY)


# ─── Report actions ─────────────────────────────────────────────────────────

def update_report_status(db, doc_id: str, status: str, note: str, admin_email: str,
                         dup_of: str = '') -> Dict[str, str]:
    """Port of adminUpdateCivicReport. Returns {'from', 'to'}."""
    if status not in STATUSES:
        raise CivicAdminError('Pick a valid status.')
    note = clean_text(note, MAX_ADMIN_NOTE)
    if status in ('rejected', 'duplicate') and not note:
        raise CivicAdminError('Add a short note for the reporter before closing this report.')
    dup_of = clean_text(dup_of, 64) or ''
    report_ref = db.collection(REPORTS).document(doc_id)
    priv_ref = db.collection(PRIVATE).document(doc_id)

    def fn(tx):
        snap, priv_snap = _get(report_ref, tx), _get(priv_ref, tx)
        if not snap.exists:
            raise CivicAdminError('That report no longer exists.')
        data = snap.to_dict() or {}
        priv = (priv_snap.to_dict() or {}) if priv_snap.exists else {}
        current = str(data.get('status') or '')
        if not can_transition(current, status):
            raise CivicAdminError(
                f'A {STATUS_LABELS.get(current, current).lower()} report cannot be moved to '
                f'{STATUS_LABELS.get(status, status).lower()}. Reload the page; it may have changed.')
        now = _now()
        update: Dict[str, Any] = {
            'status': status,
            'reviewedBy': admin_email or 'admin',
            'timeline': firestore.ArrayUnion([{'status': status, 'at': now, 'note': note or None}]),
            'updatedAt': firestore.SERVER_TIMESTAMP,
        }
        if note:
            update['resolutionNote'] = note
        if status in TERMINAL:
            close_at = now + EVIDENCE_AFTER_CLOSE
            existing = _as_datetime(data.get('evidenceDeleteAfter'))
            if not existing or existing > close_at:
                update['evidenceDeleteAfter'] = close_at
        if status == 'duplicate' and dup_of:
            update['dupOf'] = dup_of
        tx.update(report_ref, update)

        alert_id = priv.get('alertId')
        if alert_id and status in ('rejected', 'duplicate'):
            tx.update(db.collection(ALERTS).document(alert_id), {
                'ownerStatus': 'resolved',
                'closedReason': status,
                'updatedAt': firestore.SERVER_TIMESTAMP,
            })
        return {
            'from': current,
            'reporter': data.get('reporterUid') or '',
            'abuse': priv.get('abuseSuspected') is True,
        }

    review = _run_tx(db, fn)

    if not review['abuse'] and status == 'verified':
        award_points(db, review['reporter'], doc_id, 'report_verified', POINTS['report_verified'])
    if not review['abuse'] and status == 'resolved':
        award_points(db, review['reporter'], doc_id, 'report_resolved', POINTS['report_resolved'])
    if status in ('rejected', 'duplicate'):
        revoke_report_points(db, review['reporter'], doc_id)

    _admin_log(db, doc_id, admin_email, note, **{'from': review['from'], 'to': status})
    if status == 'resolved':
        _bump_stats(db, {'resolvedReports': 1})
    if review['from'] == 'resolved':
        _bump_stats(db, {'resolvedReports': -1})
    _invalidate()
    return {'from': review['from'], 'to': status}


def set_abuse_flag(db, doc_id: str, flagged: bool, admin_email: str, note: str = '') -> None:
    """While flagged, the reporter earns no points for this report."""
    priv_ref = db.collection(PRIVATE).document(doc_id)
    if not priv_ref.get().exists:
        raise CivicAdminError('That report has no private record to update.')
    priv_ref.set({
        'abuseSuspected': bool(flagged),
        'abuseReviewedBy': admin_email or 'admin',
        'abuseReviewedAt': firestore.SERVER_TIMESTAMP,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)
    _admin_log(db, doc_id, admin_email, clean_text(note, MAX_ADMIN_NOTE),
               action='Flagged for repeat reports' if flagged else 'Cleared repeat-report flag')


def resolve_dispute(db, doc_id: str, admin_email: str, note: str = '') -> None:
    """Admin has looked at the owner's dispute and is keeping the report."""
    priv_ref = db.collection(PRIVATE).document(doc_id)
    snap = priv_ref.get()
    if not snap.exists or (snap.to_dict() or {}).get('disputed') is not True:
        raise CivicAdminError('This report has no open dispute.')
    priv_ref.set({
        'disputed': False,
        'disputeReviewedBy': admin_email or 'admin',
        'disputeReviewedAt': firestore.SERVER_TIMESTAMP,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)
    _admin_log(db, doc_id, admin_email, clean_text(note, MAX_ADMIN_NOTE),
               action='Dispute reviewed, report kept')
    _invalidate()


def evidence_bucket():
    from firebase_admin import storage
    return storage.bucket()


def read_evidence(report: Dict[str, Any], index: int, bucket=None) -> Tuple[bytes, str]:
    """Bytes and content type of one evidence photo. Only paths on the report."""
    paths = report.get('evidence') or []
    if index < 0 or index >= len(paths):
        raise CivicAdminError('Photo not found.')
    path = paths[index]
    if not path.startswith('civic_evidence/'):
        raise CivicAdminError('Photo not found.')
    blob = (bucket or evidence_bucket()).blob(path)
    data = blob.download_as_bytes()
    return data, blob.content_type or 'image/jpeg'


def delete_evidence_now(db, doc_id: str, admin_email: str, bucket=None) -> int:
    snap = db.collection(REPORTS).document(doc_id).get()
    if not snap.exists:
        raise CivicAdminError('That report no longer exists.')
    paths = [str(p) for p in ((snap.to_dict() or {}).get('evidencePaths') or []) if p]
    bucket = bucket or evidence_bucket()
    deleted = 0
    for path in paths:
        if not path.startswith('civic_evidence/'):
            continue
        try:
            bucket.blob(path).delete()
            deleted += 1
        except Exception as exc:
            if getattr(exc, 'code', None) != 404:
                logger.warning('civic admin: evidence delete failed for %s: %s', path, exc)
    db.collection(REPORTS).document(doc_id).update({
        'evidencePaths': [],
        'evidenceDeleted': True,
        'evidenceDeleteAfter': None,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    })
    _admin_log(db, doc_id, admin_email, None, action=f'Deleted {len(paths)} evidence photo(s)')
    return deleted


# ─── Impact stats ───────────────────────────────────────────────────────────

STAT_FIELDS = ('totalReports', 'resolvedReports', 'ownerAcknowledgements', 'activeReporters', 'activeCampaigns')


def get_stats(db) -> Dict[str, Any]:
    snap = db.collection(STATS).document(STATS_DOC).get()
    d = (snap.to_dict() or {}) if snap.exists else {}
    out = {key: _int(d.get(key)) for key in STAT_FIELDS}
    out['updated_at'] = _as_datetime(d.get('updatedAt'))
    return out


def recount_stats(db) -> Dict[str, int]:
    """Rebuild the public impact counters from the source collections."""
    total = resolved = 0
    for s in db.collection(REPORTS).stream():
        total += 1
        if (s.to_dict() or {}).get('status') == 'resolved':
            resolved += 1
    acks = 0
    for s in db.collection(ALERTS).stream():
        d = s.to_dict() or {}
        if d.get('ownerStatus') in ('acknowledged', 'resolved') and not d.get('closedReason'):
            acks += 1
    reporters = sum(1 for _ in db.collection(RATE_LIMITS).stream())
    campaigns = count_live_campaigns(db)
    values = {
        'totalReports': total,
        'resolvedReports': resolved,
        'ownerAcknowledgements': acks,
        'activeReporters': reporters,
        'activeCampaigns': campaigns,
    }
    db.collection(STATS).document(STATS_DOC).set({**values, 'updatedAt': firestore.SERVER_TIMESTAMP}, merge=True)
    return values


# ─── Awareness campaigns ────────────────────────────────────────────────────

def normalize_campaign(doc_id: str, d: Dict[str, Any]) -> Dict[str, Any]:
    publish_at = _as_datetime(d.get('publishAt'))
    active = d.get('isActive') is not False
    now = _now()
    if not active:
        state = 'hidden'
    elif publish_at and publish_at > now:
        state = 'scheduled'
    else:
        state = 'live'
    category = d.get('category') or 'general'
    return {
        'id': doc_id,
        'title': d.get('title') or '',
        'description': d.get('description') or '',
        'cover_url': d.get('coverUrl') or '',
        'category': category,
        'category_label': AWARENESS_CATEGORIES.get(category, category),
        'link_url': d.get('linkUrl') or '',
        'publish_at': publish_at,
        'is_active': active,
        'state': state,
        'created_by': d.get('createdBy') or '',
        'created_at': _as_datetime(d.get('createdAt')),
        'updated_at': _as_datetime(d.get('updatedAt')),
    }


def list_campaigns(db) -> List[Dict[str, Any]]:
    rows = [normalize_campaign(s.id, s.to_dict() or {}) for s in db.collection(AWARENESS).stream()]
    rows.sort(key=lambda c: c['publish_at'] or c['created_at'] or datetime.min.replace(tzinfo=timezone.utc),
              reverse=True)
    return rows


def get_campaign(db, campaign_id: str) -> Optional[Dict[str, Any]]:
    snap = db.collection(AWARENESS).document(campaign_id).get()
    return normalize_campaign(snap.id, snap.to_dict() or {}) if snap.exists else None


def count_live_campaigns(db) -> int:
    return sum(1 for c in list_campaigns(db) if c['state'] == 'live')


def _refresh_campaign_stat(db) -> None:
    try:
        db.collection(STATS).document(STATS_DOC).set({
            'activeCampaigns': count_live_campaigns(db),
            'updatedAt': firestore.SERVER_TIMESTAMP,
        }, merge=True)
    except Exception as exc:
        logger.warning('civic admin: activeCampaigns refresh failed: %s', exc)


def parse_publish_at(raw: str, tz_offset_minutes: int = 330) -> Optional[datetime]:
    """`2026-11-20T09:30` from <input type=datetime-local>, in IST by default."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            naive = datetime.strptime(raw, fmt)
            return naive.replace(tzinfo=timezone(timedelta(minutes=tz_offset_minutes))).astimezone(timezone.utc)
        except ValueError:
            continue
    raise CivicAdminError('Publish time is not a valid date.')


def _upload_cover(upload, campaign_id: str) -> str:
    import cloudinary.uploader
    content_type = getattr(upload, 'content_type', '') or ''
    if not content_type.startswith('image/'):
        raise CivicAdminError('The cover must be an image (JPG, PNG or WebP).')
    if getattr(upload, 'size', 0) > 5 * 1024 * 1024:
        raise CivicAdminError('The cover image must be under 5 MB.')
    upload.seek(0)
    result = cloudinary.uploader.upload(
        upload, folder='sudotag/civic_awareness', public_id=campaign_id,
        overwrite=True, resource_type='image',
    )
    url = str(result.get('secure_url') or '')
    if not url:
        raise CivicAdminError('The cover image could not be uploaded. Try again.')
    return url


def save_campaign(db, campaign_id: Optional[str], form: Dict[str, Any], admin_email: str,
                  upload=None) -> str:
    title = clean_text(form.get('title'), 80)
    description = (form.get('description') or '').strip()[:1000]
    if not title:
        raise CivicAdminError('Give the campaign a title.')
    if not description:
        raise CivicAdminError('Add a short description.')
    category = form.get('category') or 'general'
    if category not in AWARENESS_CATEGORIES:
        category = 'general'
    link = (form.get('link_url') or '').strip()[:500]
    if link and not link.startswith('https://'):
        raise CivicAdminError('The link must start with https://')
    cover = (form.get('cover_url') or '').strip()[:500]
    if cover and not cover.startswith('https://'):
        raise CivicAdminError('The cover image URL must start with https://')
    publish_at = parse_publish_at(form.get('publish_at') or '')

    ref = db.collection(AWARENESS).document(campaign_id) if campaign_id else db.collection(AWARENESS).document()
    if campaign_id and not ref.get().exists:
        raise CivicAdminError('That campaign no longer exists.')
    if upload:
        cover = _upload_cover(upload, ref.id)
    if form.get('remove_cover'):
        cover = ''

    data: Dict[str, Any] = {
        'title': title,
        'description': description,
        'category': category,
        'coverUrl': cover or None,
        'linkUrl': link or None,
        # The app orders by publishAt, so a campaign without one never shows.
        'publishAt': publish_at or _now(),
        'isActive': bool(form.get('is_active')),
        'updatedAt': firestore.SERVER_TIMESTAMP,
        'updatedBy': admin_email or 'admin',
    }
    if campaign_id:
        ref.set(data, merge=True)
    else:
        data.update({'createdBy': admin_email or 'admin', 'createdAt': firestore.SERVER_TIMESTAMP})
        ref.set(data)
    _refresh_campaign_stat(db)
    return ref.id


def set_campaign_active(db, campaign_id: str, active: bool, admin_email: str) -> None:
    ref = db.collection(AWARENESS).document(campaign_id)
    if not ref.get().exists:
        raise CivicAdminError('That campaign no longer exists.')
    ref.set({'isActive': bool(active), 'updatedAt': firestore.SERVER_TIMESTAMP,
             'updatedBy': admin_email or 'admin'}, merge=True)
    _refresh_campaign_stat(db)


def delete_campaign(db, campaign_id: str) -> None:
    db.collection(AWARENESS).document(campaign_id).delete()
    _refresh_campaign_stat(db)


# ─── Civic Points admin ─────────────────────────────────────────────────────

def normalize_member(uid: str, d: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    level = d.get('level') or level_for(d.get('total'))[0]
    return {
        'uid': uid,
        'total': _int(d.get('total')),
        'month_points': _int(d.get('monthPoints')) if d.get('monthKey') == month_key(now) else 0,
        'level': level,
        'level_name': LEVEL_NAMES.get(level, level),
        'show': d.get('showOnLeaderboard') is True,
        'public_name': d.get('publicName') or '',
        'name_hidden_by_admin': d.get('nameHiddenByAdmin') is True,
        'leaderboard_id': d.get('leaderboardId') or '',
        'updated_at': _as_datetime(d.get('updatedAt')),
    }


def list_members(db, query: str = '', limit: int = 200) -> List[Dict[str, Any]]:
    try:
        snaps = list(db.collection(POINTS_COLL)
                     .order_by('total', direction=firestore.Query.DESCENDING).limit(limit).stream())
    except Exception as exc:
        logger.warning('civic admin: ordered points read failed (%s)', exc)
        snaps = list(db.collection(POINTS_COLL).limit(limit).stream())
    members = [normalize_member(s.id, s.to_dict() or {}) for s in snaps]
    members.sort(key=lambda m: m['total'], reverse=True)
    users = get_users(db, [m['uid'] for m in members])
    for m in members:
        m['user'] = users.get(m['uid'], {})
    needle = (query or '').strip().lower()
    if needle:
        members = [m for m in members if needle in ' '.join([
            m['uid'], m['public_name'], m['user'].get('name', ''), m['user'].get('email', ''),
            m['user'].get('phone', '')]).lower()]
    return members


def get_leaderboard(db, month: str, limit: int = 20) -> List[Dict[str, Any]]:
    rows = []
    try:
        snaps = (db.collection(LEADERBOARD)
                 .where(filter=FieldFilter('monthKey', '==', month))
                 .order_by('monthPoints', direction=firestore.Query.DESCENDING)
                 .limit(limit).stream())
        for s in snaps:
            d = s.to_dict() or {}
            if _int(d.get('monthPoints')) <= 0:
                continue
            rows.append({'id': s.id, 'name': d.get('publicName') or 'SudoTag member',
                         'month_points': _int(d.get('monthPoints')), 'total': _int(d.get('total')),
                         'level_name': LEVEL_NAMES.get(d.get('level'), d.get('level') or '')})
    except Exception as exc:
        logger.warning('civic admin: leaderboard read failed: %s', exc)
    return rows


def get_member(db, uid: str, ledger_limit: int = 100) -> Optional[Dict[str, Any]]:
    snap = db.collection(POINTS_COLL).document(uid).get()
    member = normalize_member(uid, (snap.to_dict() or {}) if snap.exists else {})
    member['exists'] = snap.exists
    ledger = []
    try:
        stream = (db.collection(POINTS_COLL).document(uid).collection('ledger')
                  .order_by('at', direction=firestore.Query.DESCENDING).limit(ledger_limit).stream())
        for s in stream:
            d = s.to_dict() or {}
            reason = d.get('reason') or ''
            ledger.append({
                'id': s.id,
                'reason': reason,
                'label': LEDGER_LABELS.get(reason, reason or 'Points'),
                'points': _int(d.get('points')),
                'requested': d.get('requested'),
                'report_doc_id': d.get('reportDocId') or '',
                'note': d.get('note') or '',
                'by': d.get('adminEmail') or '',
                'at': _as_datetime(d.get('at')),
            })
    except Exception as exc:
        logger.warning('civic admin: ledger read failed: %s', exc)
    member['ledger'] = ledger
    member['user'] = get_users(db, [uid]).get(uid, {})
    reports = []
    try:
        for s in db.collection(REPORTS).where(filter=FieldFilter('reporterUid', '==', uid)).stream():
            reports.append(normalize_report(s.id, s.to_dict() or {}))
    except Exception as exc:
        logger.warning('civic admin: member reports read failed: %s', exc)
    reports.sort(key=lambda r: r['created_at'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    member['reports'] = reports
    return member


def adjust_points(db, uid: str, amount, reason: str, admin_email: str) -> int:
    """Manual correction. Not capped daily; totals never go below zero."""
    try:
        amount = int(str(amount).strip())
    except (TypeError, ValueError):
        raise CivicAdminError('Enter a whole number of points, e.g. 10 or -5.')
    if amount == 0 or abs(amount) > MAX_ADJUST_POINTS:
        raise CivicAdminError(f'Points must be between -{MAX_ADJUST_POINTS} and {MAX_ADJUST_POINTS}, and not 0.')
    reason = clean_text(reason, MAX_ADJUST_REASON)
    if not reason:
        raise CivicAdminError('Add a reason for the adjustment.')
    if not db.collection('users').document(uid).get().exists:
        raise CivicAdminError('No SudoTag user has that ID.')
    points_ref = db.collection(POINTS_COLL).document(uid)
    ledger_ref = points_ref.collection('ledger').document(f'admin_{int(_now().timestamp() * 1000)}_{secrets.token_hex(3)}')

    def fn(tx):
        snap = _get(points_ref, tx)
        prev = (snap.to_dict() or {}) if snap.exists else {}
        nxt, applied = apply_points(prev, amount, _now(), respect_cap=False)
        _write_points(db, tx, uid, prev, nxt)
        tx.set(ledger_ref, {
            'reason': 'admin_adjustment',
            'points': applied,
            'requested': amount,
            'note': reason,
            'adminEmail': admin_email or 'admin',
            'at': firestore.SERVER_TIMESTAMP,
        })
        return applied

    return _run_tx(db, fn)


def hide_public_name(db, uid: str, admin_email: str) -> None:
    """Take a member's name off the leaderboard (e.g. an offensive name)."""
    points_ref = db.collection(POINTS_COLL).document(uid)

    def fn(tx):
        snap = _get(points_ref, tx)
        if not snap.exists:
            raise CivicAdminError('This member has no Civic Points yet.')
        prev = snap.to_dict() or {}
        nxt, _ = apply_points(prev, 0, _now())
        _write_points(db, tx, uid, prev, nxt, show=False, public_name=None)
        tx.set(points_ref, {'nameHiddenByAdmin': True, 'nameHiddenBy': admin_email or 'admin',
                            'nameHiddenAt': firestore.SERVER_TIMESTAMP}, merge=True)

    _run_tx(db, fn)
