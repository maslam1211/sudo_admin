"""Copy user data Firestore -> PostgreSQL (read-only on Firestore).

Subcollections under users/{uid} are discovered with `collections()`, the
same walk as the Phase 1 mirror, so nothing under a user is skipped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.utils import timezone as dj_tz

from api.mirror import decode, encode

from .models import (
    MASTER_POSTGRES, AccountsImport, BlockedUser, DailyUsage, FamilyMember, UserProfile, UserSettings,
    UserSubDocument,
)

logger = logging.getLogger(__name__)

SETTINGS_SUB = 'user-settings'
SETTINGS_FIELDS = {
    'enableCall': 'enable_call', 'enableChat': 'enable_chat', 'enableNormalCall': 'enable_normal_call',
    'enablePushNotification': 'enable_push_notification', 'enableSms': 'enable_sms',
    'showMobileNumber': 'show_mobile_number', 'showProfilePicture': 'show_profile_picture',
    'showVehicleImage': 'show_vehicle_image',
}


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _s(value, n) -> str:
    return str(value or '')[:n]


def _int_or_none(value):
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def profile_columns(d: dict) -> dict:
    return {
        'full_name': _s(d.get('fullName'), 200),
        'contact_number': _s(d.get('contactNumber') or d.get('mobileNumber'), 40),
        'email_address': _s(d.get('emailAddress'), 254).lower(),
        'city': _s(d.get('city'), 100),
        'profile_picture': _s(d.get('profilePicture'), 1000),
        'role_id': _s(d.get('roleId'), 32),
        'profile_complete': d.get('profileComplete') is True,
        'account_deleted': d.get('accountDeleted') is True,
        'app_platform': _s(d.get('appPlatform'), 16),
        'app_build': _int_or_none(d.get('appBuild')),
        'created_at': _dt(d.get('createdAt')),
    }


def _settings_columns(d: dict) -> dict:
    return {col: (d.get(key) if isinstance(d.get(key), bool) else None) for key, col in SETTINGS_FIELDS.items()}


def _now():
    return dj_tz.now()


def store_profile(uid: str, data: dict) -> None:
    existing = UserProfile.objects.filter(uid=uid).first()
    if existing and existing.master == MASTER_POSTGRES:
        return  # PostgreSQL masters this profile; never overwrite from Firestore
    UserProfile.objects.update_or_create(uid=uid, defaults={
        **profile_columns(data), 'document': encode(data), 'synced_at': _now(), 'deleted_at': None})


def _walk_subcollections(ref, base_path: str, uid: str, seen_sub: set) -> None:
    for sub in ref.collections():
        sub_path = f'{base_path}/{sub.id}'
        streamed = set()
        for snap in sub.stream():
            streamed.add(snap.id)
            _store_sub(uid, sub_path, snap.id, snap.to_dict() or {}, seen_sub)
            _walk_subcollections(snap.reference, f'{sub_path}/{snap.id}', uid, seen_sub)
        for child in sub.list_documents():
            if child.id not in streamed:   # holds only subcollections
                _walk_subcollections(child, f'{sub_path}/{child.id}', uid, seen_sub)


def _store_sub(uid: str, sub_path: str, doc_id: str, data: dict, seen_sub: set) -> None:
    path = f'{sub_path}/{doc_id}'
    parts = path.split('/')
    subcollection = parts[2]
    if len(parts) == 4 and subcollection == SETTINGS_SUB and doc_id == uid:
        UserSettings.objects.update_or_create(uid=uid, defaults={
            'doc_id': doc_id, **_settings_columns(data), 'document': encode(data),
            'synced_at': _now(), 'deleted_at': None})
        seen_sub.add(('settings', uid))
        return
    UserSubDocument.objects.update_or_create(path=path, defaults={
        'uid': uid, 'subcollection': subcollection, 'document': encode(data),
        'synced_at': _now(), 'deleted_at': None})
    seen_sub.add(('sub', path))


def import_user(db, uid: str) -> None:
    """One user's profile, settings and every subcollection document."""
    ref = db.collection('users').document(uid)
    snap = ref.get()
    seen: set = set()
    if snap.exists:
        store_profile(uid, snap.to_dict() or {})
    else:
        # Document deleted (its subcollections may remain): keep the row and
        # its last data, marked deleted, unless PostgreSQL masters it.
        UserProfile.objects.filter(uid=uid, deleted_at__isnull=True).exclude(master=MASTER_POSTGRES) \
            .update(deleted_at=_now())
    _walk_subcollections(ref, f'users/{uid}', uid, seen)
    _mark_children_gone(uid, seen)


def _mark_user_gone(uid: str) -> None:
    now = _now()
    UserProfile.objects.filter(uid=uid, deleted_at__isnull=True).exclude(master=MASTER_POSTGRES) \
        .update(deleted_at=now)
    UserSettings.objects.filter(uid=uid, deleted_at__isnull=True).update(deleted_at=now)
    UserSubDocument.objects.filter(uid=uid, deleted_at__isnull=True).update(deleted_at=now)


def _mark_children_gone(uid: str, seen: set) -> None:
    now = _now()
    if ('settings', uid) not in seen:
        UserSettings.objects.filter(uid=uid, deleted_at__isnull=True).update(deleted_at=now)
    paths = [p for kind, p in seen if kind == 'sub']
    UserSubDocument.objects.filter(uid=uid, deleted_at__isnull=True).exclude(path__in=paths) \
        .update(deleted_at=now)


TOP_LEVEL = [
    ('blocked_users', BlockedUser, 'id',
     lambda d: {'blocker_id': _s(d.get('blockerId'), 128), 'blocked_user_id': _s(d.get('blockedUserId'), 128),
                'blocked_at': _dt(d.get('blockedAt'))}),
    ('family_members', FamilyMember, 'id',
     lambda d: {'owner_id': _s(d.get('ownerId'), 128), 'name': _s(d.get('name'), 200),
                'contact_number': _s(d.get('contactNumber'), 40), 'created_at': _dt(d.get('createdAt'))}),
    ('daily_usage', DailyUsage, 'uid', lambda d: {}),
]


def import_everything(db) -> dict:
    stats = {}
    users_coll = db.collection('users')
    uids = set()
    for snap in users_coll.stream():
        uids.add(snap.id)
    for ref in users_coll.list_documents():
        uids.add(ref.id)   # parents with only subcollections
    for uid in sorted(uids):
        import_user(db, uid)
    gone = UserProfile.objects.filter(deleted_at__isnull=True).exclude(uid__in=uids) \
        .exclude(master=MASTER_POSTGRES).values_list('uid', flat=True)
    for uid in list(gone):
        _mark_user_gone(uid)
    stats['users'] = len(uids)
    stats['settings'] = UserSettings.objects.filter(deleted_at__isnull=True).count()
    stats['sub_documents'] = UserSubDocument.objects.filter(deleted_at__isnull=True).count()

    for collection, model, key, columns in TOP_LEVEL:
        seen = []
        for snap in db.collection(collection).stream():
            data = snap.to_dict() or {}
            seen.append(snap.id)
            model.objects.update_or_create(**{key: snap.id}, defaults={
                **columns(data), 'document': encode(data), 'synced_at': _now(), 'deleted_at': None})
        marked = model.objects.filter(deleted_at__isnull=True).exclude(pk__in=seen).update(deleted_at=_now())
        stats[collection] = {'imported': len(seen), 'marked_deleted': marked}
    AccountsImport.objects.update_or_create(id='full', defaults={'finished_at': _now()})
    return stats


def postgres_ready() -> bool:
    try:
        return AccountsImport.objects.filter(id='full').exists()
    except Exception:
        return False


def profile_document(uid: str) -> dict | None:
    row = UserProfile.objects.filter(uid=uid, deleted_at__isnull=True).first()
    return decode(row.document) if row else None
