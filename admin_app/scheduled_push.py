"""Scheduled push notifications for one customer, stored in Firestore."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from firebase_admin import firestore

logger = logging.getLogger(__name__)

COLLECTION = 'scheduled_push_notifications'
IST = ZoneInfo('Asia/Kolkata')
INTERVAL_CHOICES = (
    (0, 'Once'),
    (15, 'Every 15 minutes'),
    (60, 'Every hour'),
    (360, 'Every 6 hours'),
    (1440, 'Every day'),
    (10080, 'Every week'),
)
ALLOWED_INTERVALS = {minutes for minutes, _label in INTERVAL_CHOICES}

_started = False
_tick_lock = threading.Lock()


def _as_utc(value):
    if value is None:
        return None
    if hasattr(value, 'to_datetime'):
        try:
            value = value.to_datetime()
        except Exception:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_local_datetime(raw: str) -> datetime | None:
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(timezone.utc)


def format_local(value) -> str:
    moment = _as_utc(value)
    if moment is None:
        return ''
    return moment.astimezone(IST).strftime('%d %b %Y, %I:%M %p')


def resolve_user(db, raw: str) -> str:
    text = str(raw or '').strip()
    if not text:
        return ''
    if '@' in text:
        for value in (text.lower(), text):
            matches = list(
                db.collection('users').where('emailAddress', '==', value).limit(1).stream()
            )
            if matches:
                return matches[0].id
        return ''
    snap = db.collection('users').document(text).get()
    return text if snap.exists else ''


def create_schedule(
    db,
    *,
    uid,
    title,
    message,
    link_url,
    image_url,
    next_run_at,
    interval_minutes,
    end_at,
    audience='user',
    button_text='',
):
    if interval_minutes not in ALLOWED_INTERVALS:
        raise ValueError('Choose a valid interval.')
    if end_at is not None and end_at <= next_run_at:
        raise ValueError('The end time must be after the first send time.')
    everyone = audience == 'all'
    ref = db.collection(COLLECTION).document()
    ref.set({
        'audience': 'all' if everyone else 'user',
        'uid': '' if everyone else uid,
        'title': title,
        'message': message,
        'linkUrl': link_url,
        'imageUrl': image_url,
        'buttonText': button_text or 'Open',
        'intervalMinutes': int(interval_minutes),
        'nextRunAt': next_run_at,
        'endAt': end_at,
        'enabled': True,
        'sentCount': 0,
        'lastError': '',
        'createdAt': firestore.SERVER_TIMESTAMP,
    })
    return ref.id


def list_schedules(db) -> list[dict]:
    rows = []
    try:
        docs = db.collection(COLLECTION).stream()
    except Exception as exc:
        logger.warning('scheduled push list failed: %s', exc)
        return rows
    for doc in docs:
        data = doc.to_dict() or {}
        minutes = int(data.get('intervalMinutes') or 0)
        label = dict(INTERVAL_CHOICES).get(minutes, 'Once')
        rows.append({
            'id': doc.id,
            'uid': 'All customers' if data.get('audience') == 'all' else (data.get('uid') or ''),
            'title': data.get('title') or '',
            'message': data.get('message') or '',
            'interval': label,
            'enabled': data.get('enabled') is True,
            'next_run': format_local(data.get('nextRunAt')),
            'end_at': format_local(data.get('endAt')),
            'sent_count': int(data.get('sentCount') or 0),
            'last_error': data.get('lastError') or '',
            'created': _as_utc(data.get('createdAt')) or datetime.min.replace(tzinfo=timezone.utc),
        })
    rows.sort(key=lambda row: row['created'], reverse=True)
    for row in rows:
        row.pop('created', None)
    return rows


def cancel_schedule(db, schedule_id: str) -> None:
    db.collection(COLLECTION).document(schedule_id).set(
        {'enabled': False, 'updatedAt': firestore.SERVER_TIMESTAMP},
        merge=True,
    )


def run_due_schedules(db, now=None) -> int:
    """Send every enabled schedule whose next time has arrived."""
    if not _tick_lock.acquire(blocking=False):
        return 0
    try:
        return _run_due(db, now or datetime.now(timezone.utc))
    finally:
        _tick_lock.release()


def _run_due(db, now: datetime) -> int:
    from .fcm_push import send_push_to_user

    sent = 0
    for doc in db.collection(COLLECTION).where('enabled', '==', True).stream():
        data = doc.to_dict() or {}
        next_run = _as_utc(data.get('nextRunAt'))
        if next_run is None or next_run > now:
            continue
        end_at = _as_utc(data.get('endAt'))
        if end_at is not None and next_run > end_at:
            doc.reference.set({'enabled': False}, merge=True)
            continue
        if data.get('audience') == 'all':
            from .promotion_notification_views import send_promotion_to_customers

            broadcast = send_promotion_to_customers(
                db,
                {
                    'title': data.get('title') or '',
                    'message': data.get('message') or '',
                    'linkUrl': data.get('linkUrl') or '',
                    'imageUrl': data.get('imageUrl') or '',
                    'buttonText': data.get('buttonText') or 'Open',
                },
            )
            result = {
                'success': int(broadcast.get('sent') or 0) > 0,
                'error': '' if int(broadcast.get('sent') or 0) > 0 else 'SEND_FAILED',
            }
        else:
            result = send_push_to_user(
                db,
                user_id=str(data.get('uid') or ''),
                title=str(data.get('title') or ''),
                body=str(data.get('message') or ''),
                data={
                    'type': 'promotion',
                    'notificationType': 'promotion',
                    'linkUrl': str(data.get('linkUrl') or ''),
                    'imageUrl': str(data.get('imageUrl') or ''),
                },
                store_inbox=True,
            )
        interval = int(data.get('intervalMinutes') or 0)
        update = {
            'lastSentAt': firestore.SERVER_TIMESTAMP,
            'lastError': '' if result.get('success') else str(result.get('error') or 'SEND_FAILED'),
        }
        if result.get('success'):
            update['sentCount'] = int(data.get('sentCount') or 0) + 1
            sent += 1
        if interval <= 0 or not result.get('success'):
            update['enabled'] = False
        else:
            following = next_run + timedelta(minutes=interval)
            if end_at is not None and following > end_at:
                update['enabled'] = False
            else:
                update['nextRunAt'] = following
        doc.reference.set(update, merge=True)
    return sent


def start_scheduler():
    """Check due user pushes about once a minute while this server is running."""
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            try:
                from .views import db
                run_due_schedules(db)
            except Exception:
                logger.exception('scheduled push tick failed')
            threading.Event().wait(60)

    threading.Thread(target=loop, name='scheduled-push', daemon=True).start()
