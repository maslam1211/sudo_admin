"""The signed-in user's own data through the API (Phase 4a writes).

Port of the app's writes in lib/data/firestore_services/user_store.dart,
profile.dart, blocked_users_store.dart, family_member_store.dart and the
password / civic-terms / phone-login merges. Firestore `users/{uid}` is
still read by Cloud Functions, security rules, the admin panel and other
users' apps, so every write goes to Firestore (same field names, same
legacy-alias clean-up) and the result is copied to PostgreSQL at once.

Only the fields below can be changed here. The app used to be able to write
any field on its own document (roleId, mustChangePassword, referral and
wallet fields…); through the API it cannot.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from api.errors import ApiError

from . import sync
from .models import BlockedUser, FamilyMember, UserProfile, UserSettings

logger = logging.getLogger(__name__)

USERS = 'users'

# lib/data/constants/user_firestore_field_aliases.dart
CONTACT_ALIASES = ['contact_number', 'mobileNumber', 'mobile_number', 'registered_phone', 'profile_phone',
                   'user_mobile', 'phone_number', 'primary_phone', 'owner_phone', 'contact_phone',
                   'registeredPhone', 'profilePhone', 'userMobile', 'phoneNumber', 'primaryPhone', 'ownerPhone',
                   'registeredMobile', 'registered_mobile', 'mobile', 'phone']
EMERGENCY_ALIASES = ['default_emergency_contact', 'emergency_contact', 'emergency_contact_number',
                     'emergencyPhone', 'emergency_phone', 'safetyEmergencyContact', 'safety_emergency_contact',
                     'safety_profile_emergency', 'safety_profile_emergency_contact', 'sosContact', 'sos_contact',
                     'iceContact', 'ice_contact', 'emergencyContact']
PROFILE_DUPLICATES = ['blood_group', 'contact_number', 'mobile_number', 'mobileNumber', 'registered_phone',
                      'profile_phone', 'user_mobile', 'email', 'role', 'default_emergency_contact',
                      'emergency_contact', 'admin_added_user', 'adminUserAdded', 'admin_user_added']

TEXT_FIELDS = {   # field -> max length
    'fullName': 80, 'city': 100, 'street': 200, 'district': 100,
    'displayAddress': 300, 'formattedAddress': 300,
}
LIVE_STATUSES = {'available', 'busy', 'sleeping', 'driving', 'out_of_station', 'do_not_disturb', 'custom'}
SETTINGS_KEYS = tuple(sync.SETTINGS_FIELDS)
DEFAULT_SETTINGS = {k: True for k in SETTINGS_KEYS}
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_FAMILY = 20


def _fs():
    from firebase_admin import firestore

    return firestore


def _now():
    return datetime.now(timezone.utc)


def normalize_mobile(raw) -> str:
    """IndianPhoneNumberUtils.normalizeIndianMobileForStorage."""
    trimmed = str(raw or '').strip()
    if not trimmed or trimmed.lower() in ('not available', 'n/a'):
        return trimmed
    digits = re.sub(r'\D', '', trimmed)
    if not digits:
        return trimmed
    return digits[-10:] if len(digits) > 10 else digits


def normalize_email(raw) -> str:
    return str(raw or '').strip().lower()


def profile_complete(full_name, email, contact) -> bool:
    return bool(str(full_name or '').strip() and str(email or '').strip() and str(contact or '').strip())


def _deletes(keys) -> dict:
    return {k: _fs().DELETE_FIELD for k in keys}


def _user_ref(db, uid):
    return db.collection(USERS).document(uid)


def _current(db, uid) -> dict:
    snap = _user_ref(db, uid).get()
    return (snap.to_dict() or {}) if snap.exists else {}


def _copy(db, uid) -> None:
    try:
        sync.import_user(db, uid)
    except Exception:
        logger.exception('accounts: copy of %s to PostgreSQL failed (worker will retry)', uid)


def me(uid: str) -> dict:
    """Profile and settings from PostgreSQL (refreshed after every API write)."""
    from api.mirror import decode

    profile = UserProfile.objects.filter(uid=uid, deleted_at__isnull=True).first()
    settings = UserSettings.objects.filter(uid=uid, deleted_at__isnull=True).first()
    return {
        'exists': profile is not None,
        'profile': _json(decode(profile.document)) if profile else None,
        'settings': {**DEFAULT_SETTINGS, **(_json(decode(settings.document)) if settings else {})},
    }


def _json(data: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items()}


def assert_email_free(db, email: str, uid: str) -> None:
    """Same check as UserStore.assertEmailUniqueForOwner (Firestore is still the shared record)."""
    if not email:
        return
    for snap in db.collection(USERS).where('emailAddress', '==', email).limit(10).stream():
        if snap.id != uid:
            raise ApiError('already-exists',
                           'This email is already linked to another SudoTag account. Please use a different email.')


# ─── profile ─────────────────────────────────────────────────────────────────
def complete_profile(db, uid: str, *, full_name: str, email: str = '', phone: str = '') -> dict:
    """UserStore.createUserProfile: first profile save after sign-up (merge)."""
    full_name = (full_name or '').strip()[:80]
    if not full_name:
        raise ApiError('invalid-argument', 'Please enter your name.')
    email = normalize_email(email)
    if email and not EMAIL_RE.match(email):
        raise ApiError('invalid-argument', 'Please enter a valid email address.')
    assert_email_free(db, email, uid)
    existing = _current(db, uid)
    phone = normalize_mobile(phone) or normalize_mobile(existing.get('contactNumber'))
    email = email or normalize_email(existing.get('emailAddress'))
    patch = {
        'id': uid,
        'fullName': full_name,
        'emailAddress': email,
        'enableIdCheck': existing.get('enableIdCheck', True),
        'roleId': existing.get('roleId', 0),
        'mustChangePassword': existing.get('mustChangePassword', False),
        'profileComplete': profile_complete(full_name, email, phone),
        **_deletes(CONTACT_ALIASES),
    }
    if phone:
        patch['contactNumber'] = phone
    if existing.get('createdAt') is None:
        patch['createdAt'] = _now()
    _user_ref(db, uid).set(patch, merge=True)
    _copy(db, uid)
    return me(uid)


def update_profile(db, uid: str, changes: dict) -> dict:
    """Profile edit, safety fields, live status, picture. Only keys present
    are changed; an empty bloodGroup / defaultEmergencyContact removes it."""
    existing = _current(db, uid)
    if not existing:
        raise ApiError('failed-precondition', 'Create your profile first.')
    patch: dict = {}
    for key, limit in TEXT_FIELDS.items():
        if key in changes and changes[key] is not None:
            patch[key] = str(changes[key]).strip()[:limit]
    if 'fullName' in patch and not patch['fullName']:
        raise ApiError('invalid-argument', 'Please enter your name.')

    if changes.get('emailAddress') is not None:
        email = normalize_email(changes['emailAddress'])
        if email and not EMAIL_RE.match(email):
            raise ApiError('invalid-argument', 'Please enter a valid email address.')
        assert_email_free(db, email, uid)
        patch['emailAddress'] = email
    if changes.get('contactNumber') is not None:
        patch['contactNumber'] = normalize_mobile(changes['contactNumber'])
        patch.update(_deletes(CONTACT_ALIASES))
    if changes.get('profilePicture') is not None:
        url = str(changes['profilePicture']).strip()
        if url and not url.startswith('https://'):
            raise ApiError('invalid-argument', 'Profile picture must be an https link.')
        patch['profilePicture'] = url[:1000]

    if 'bloodGroup' in changes:
        bg = str(changes.get('bloodGroup') or '').strip()[:8]
        patch['bloodGroup'] = bg or _fs().DELETE_FIELD
        patch['blood_group'] = _fs().DELETE_FIELD
    if 'defaultEmergencyContact' in changes:
        em = normalize_mobile(changes.get('defaultEmergencyContact'))
        patch['defaultEmergencyContact'] = em or _fs().DELETE_FIELD
        patch.update(_deletes(EMERGENCY_ALIASES))

    if changes.get('liveStatus') is not None:
        status = str(changes['liveStatus'])
        if status not in LIVE_STATUSES:
            raise ApiError('invalid-argument', 'Unknown live status.')
        patch['liveStatus'] = status
        patch['liveStatusUpdatedAt'] = _fs().SERVER_TIMESTAMP
        if status == 'custom':
            text = str(changes.get('liveStatusCustomText') or '').strip()[:120]
            if not text:
                raise ApiError('invalid-argument', 'Please enter a custom status message.')
            patch['liveStatusCustomText'] = text
        else:
            patch['liveStatusCustomText'] = _fs().DELETE_FIELD

    if not patch:
        return me(uid)
    if changes.get('fullProfile'):
        patch.update({k: _fs().DELETE_FIELD for k in PROFILE_DUPLICATES if k not in patch})
    merged = {**existing, **{k: v for k, v in patch.items() if isinstance(v, str)}}
    patch['profileComplete'] = profile_complete(merged.get('fullName'), merged.get('emailAddress'),
                                                merged.get('contactNumber'))
    _user_ref(db, uid).update(patch)
    _copy(db, uid)
    return me(uid)


def password_changed(db, uid: str) -> dict:
    _user_ref(db, uid).set({'mustChangePassword': False, 'passwordUpdatedAt': _fs().SERVER_TIMESTAMP}, merge=True)
    _copy(db, uid)
    return me(uid)


def accept_civic_terms(db, uid: str, version: str) -> dict:
    version = (version or '').strip()[:20]
    if not version:
        raise ApiError('invalid-argument', 'Missing terms version.')
    _user_ref(db, uid).set({'civicTermsAcceptedVersion': version,
                            'civicTermsAcceptedAt': _fs().SERVER_TIMESTAMP}, merge=True)
    _copy(db, uid)
    return me(uid)


def record_verified_phone(db, uid: str, phone_e164: str) -> None:
    """After an OTP login the server knows the number is real: store it (the
    app used to write this itself)."""
    national = normalize_mobile(phone_e164)
    if len(national) != 10:
        return
    try:
        _user_ref(db, uid).set({'contactNumber': national, **_deletes(CONTACT_ALIASES)}, merge=True)
        _copy(db, uid)
    except Exception:
        logger.exception('accounts: could not store verified phone for %s', uid)


# ─── settings ────────────────────────────────────────────────────────────────
def update_settings(db, uid: str, changes: dict) -> dict:
    """UserStore.mergeUserSettingsFields: only the toggles sent are changed."""
    fields = {k: v for k, v in changes.items() if k in SETTINGS_KEYS}
    if not fields or not all(isinstance(v, bool) for v in fields.values()):
        raise ApiError('invalid-argument', 'Settings must be true or false.')
    ref = _user_ref(db, uid).collection(sync.SETTINGS_SUB).document(uid)
    if not ref.get().exists:
        fields = {**DEFAULT_SETTINGS, 'id': uid, **fields}   # first save writes the defaults too
    ref.set(fields, merge=True)
    _copy(db, uid)
    return me(uid)


# ─── blocked users ───────────────────────────────────────────────────────────
def _import_top(db, collection: str, doc_id: str) -> None:
    from api.mirror import encode

    for name, model, key, columns in sync.TOP_LEVEL:
        if name != collection:
            continue
        snap = db.collection(collection).document(doc_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            model.objects.update_or_create(**{key: doc_id}, defaults={
                **columns(data), 'document': encode(data), 'synced_at': _now(), 'deleted_at': None})
        else:
            model.objects.filter(pk=doc_id, deleted_at__isnull=True).update(deleted_at=_now())


def _blocks(db, uid: str, other: str):
    return list(db.collection('blocked_users').where('blockerId', '==', uid)
                .where('blockedUserId', '==', other).stream())


def block(db, uid: str, other: str, *, name: str = '', picture: str = '') -> dict:
    other = (other or '').strip()
    if not other or other == uid:
        raise ApiError('invalid-argument', 'Choose someone to block.')
    if not _blocks(db, uid, other):
        _, ref = db.collection('blocked_users').add({
            'blockerId': uid, 'blockedUserId': other, 'blockedUserName': (name or '').strip()[:80],
            'blockedUserProfilePicture': (picture or '').strip()[:1000] or None, 'blockedAt': _now()})
        _import_top(db, 'blocked_users', ref.id)
    return {'blocked': True}


def unblock(db, uid: str, other: str) -> dict:
    for snap in _blocks(db, uid, other):
        snap.reference.delete()
        _import_top(db, 'blocked_users', snap.id)
    return {'blocked': False}


def blocked_list(uid: str) -> list[dict]:
    from api.mirror import decode

    rows = BlockedUser.objects.filter(blocker_id=uid, deleted_at__isnull=True).order_by('-blocked_at')
    return [{'id': r.id, **_json(decode(r.document))} for r in rows]


# ─── family members ──────────────────────────────────────────────────────────
def _family_doc(uid: str, body: dict, created_at=None) -> dict:
    name = str(body.get('name') or '').strip()[:80]
    if not name:
        raise ApiError('invalid-argument', 'Please enter a name.')
    phone = normalize_mobile(body.get('contactNumber'))
    if len(phone) != 10 or not phone.isdigit():
        raise ApiError('invalid-argument', 'Please enter a valid 10-digit mobile number.')
    return {'ownerId': uid, 'name': name, 'relation': str(body.get('relation') or '').strip()[:40],
            'contactNumber': phone, 'createdAt': created_at or _now()}


def add_family(db, uid: str, body: dict) -> dict:
    if FamilyMember.objects.filter(owner_id=uid, deleted_at__isnull=True).count() >= MAX_FAMILY:
        raise ApiError('resource-exhausted', f'You can add up to {MAX_FAMILY} family members.')
    _, ref = db.collection('family_members').add(_family_doc(uid, body))
    _import_top(db, 'family_members', ref.id)
    return family_member(uid, ref.id)


def _own_family_ref(db, uid: str, member_id: str):
    ref = db.collection('family_members').document(member_id)
    snap = ref.get()
    if not snap.exists or (snap.to_dict() or {}).get('ownerId') != uid:
        raise ApiError('not-found', 'Family member not found.')
    return ref, snap.to_dict() or {}


def update_family(db, uid: str, member_id: str, body: dict) -> dict:
    ref, current = _own_family_ref(db, uid, member_id)
    ref.update(_family_doc(uid, body, created_at=current.get('createdAt')))
    _import_top(db, 'family_members', member_id)
    return family_member(uid, member_id)


def delete_family(db, uid: str, member_id: str) -> dict:
    ref, _ = _own_family_ref(db, uid, member_id)
    ref.delete()
    _import_top(db, 'family_members', member_id)
    return {'deleted': True}


def family_member(uid: str, member_id: str) -> dict:
    from api.mirror import decode

    row = FamilyMember.objects.get(id=member_id, owner_id=uid)
    return {'id': row.id, **_json(decode(row.document))}


def family_list(uid: str) -> list[dict]:
    from api.mirror import decode

    rows = FamilyMember.objects.filter(owner_id=uid, deleted_at__isnull=True).order_by('-created_at')
    return [{'id': r.id, **_json(decode(r.document))} for r in rows]
