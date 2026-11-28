"""Import from Firestore and read app-version data from PostgreSQL."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from django.utils import timezone as dj_tz

from api.mirror import decode, encode

from .models import AppConfig, AppRelease, AppUpdateEvent

logger = logging.getLogger(__name__)

PLATFORMS = ('android', 'ios')
CONFIG = 'appConfig'
RELEASES = 'releases'
EVENTS = 'app_update_events'


def _int(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bool(value, fallback=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ('true', '1', 'yes', 'on'):
            return True
        if s in ('false', '0', 'no', 'off'):
            return False
    return fallback


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


# ─── import ──────────────────────────────────────────────────────────────────
def import_config(db, platform: str) -> Optional[AppConfig]:
    snap = db.collection(CONFIG).document(platform).get()
    if not snap.exists:
        AppConfig.objects.filter(platform=platform).delete()
        return None
    data = snap.to_dict() or {}
    row, _ = AppConfig.objects.update_or_create(platform=platform, defaults={
        'latest_version': str(data.get('latestVersion') or '')[:40],
        'latest_build': _int(data.get('latestBuild')),
        'min_supported_build': _int(data.get('minSupportedBuild')),
        'update_enabled': _bool(data.get('updateEnabled'), True),
        'published_at': _dt(data.get('publishedAt')),
        'document': encode(data),
        'synced_at': dj_tz.now(),
    })
    return row


def import_releases(db, platform: str) -> int:
    count = 0
    for snap in db.collection(CONFIG).document(platform).collection(RELEASES).stream():
        data = snap.to_dict() or {}
        AppRelease.objects.update_or_create(id=snap.id, defaults={
            'platform': platform, 'latest_build': _int(data.get('latestBuild')),
            'published_at': _dt(data.get('publishedAt')), 'document': encode(data), 'synced_at': dj_tz.now(),
        })
        count += 1
    return count


def _event_defaults(data: dict, source: str) -> dict:
    return {
        'uid': str(data.get('uid') or '')[:128],
        'platform': str(data.get('platform') or '')[:16],
        'event': str(data.get('event') or '')[:40],
        'version': str(data.get('version') or '')[:40],
        'build': _int(data.get('build')),
        'target_build': _int(data['targetBuild']) if data.get('targetBuild') is not None else None,
        'urgency': str(data.get('urgency') or '')[:16],
        'error': str(data.get('error') or '')[:500],
        'from_build': _int(data['fromBuild']) if data.get('fromBuild') is not None else None,
        'created_at': _dt(data.get('createdAt')) or dj_tz.now(),
        'source': source,
    }


def import_events(db, limit: int = 2000) -> int:
    """Append events written by older builds straight to Firestore (by doc id)."""
    from firebase_admin import firestore

    known = set(AppUpdateEvent.objects.filter(source='firestore').values_list('id', flat=True))
    query = db.collection(EVENTS).order_by('createdAt', direction=firestore.Query.DESCENDING).limit(limit)
    new = [AppUpdateEvent(id=s.id, **_event_defaults(s.to_dict() or {}, 'firestore'))
           for s in query.stream() if s.id not in known]
    AppUpdateEvent.objects.bulk_create(new, ignore_conflicts=True)
    return len(new)


def import_everything(db) -> dict:
    out = {}
    for platform in PLATFORMS:
        out[platform] = bool(import_config(db, platform))
        out[f'{platform}_releases'] = import_releases(db, platform)
    out['events'] = import_events(db)
    return out


# ─── reads (PostgreSQL) ──────────────────────────────────────────────────────
def config_document(platform: str) -> Optional[dict]:
    row = AppConfig.objects.filter(platform=platform).first()
    return decode(row.document) if row else None


def releases(platform: str, limit: int = 20) -> list[dict]:
    rows = AppRelease.objects.filter(platform=platform).order_by('-published_at')[:limit]
    return [dict(decode(r.document), id=r.id) for r in rows]


def recent_events(platform: Optional[str] = None, limit: int = 50, errors_only: bool = False) -> list[dict]:
    q = AppUpdateEvent.objects.all()
    if platform:
        q = q.filter(platform=platform)
    rows = []
    for e in q.order_by('-created_at')[: limit * 3 if errors_only else limit]:
        rows.append({'id': e.id, 'uid': e.uid, 'platform': e.platform, 'event': e.event, 'version': e.version,
                     'build': e.build, 'targetBuild': e.target_build, 'urgency': e.urgency,
                     'error': e.error, 'fromBuild': e.from_build, 'createdAt': e.created_at})
    if errors_only:
        rows = [r for r in rows if r['error'] or str(r['event']).endswith(('failed', 'unavailable'))]
    return rows[:limit]


def record_event(*, uid: str, platform: str, data: dict) -> AppUpdateEvent:
    return AppUpdateEvent.objects.create(
        id=f'api-{uuid.uuid4().hex}',
        **{**_event_defaults({**data, 'uid': uid, 'platform': platform}, 'api'), 'created_at': dj_tz.now()},
    )
