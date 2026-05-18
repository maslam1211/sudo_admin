"""
Owner preferences on Firestore `users/{uid}` for the public QR scanner page.

Boolean flags (missing = enabled)
----------------------------------
- scannerVoiceCallEnabled — Call owner / emergency via PBX bridge
- scannerSmsEnabled — SMS to owner or emergency contact
- scannerEmergencyContactEnabled — Emergency contact path (call, SMS, modals)
- scannerPushNotificationEnabled — FCM push from the QR “Send notification” page
- scannerEmergencyCallEnabled — Voice call to the emergency contact (SMS / path may stay on)

The vehicle owner's Firebase Auth / Firestore user id is ``vehicles/{vehicleId}.ownerId``.
The scanner page loads ``users/{ownerId}`` (and any merged settings keyed by that same
id, e.g. ``userSettings/{ownerId}``) so notification toggles always follow the **owner
user id**, not the QR document's optional ``userID`` field.

When **multiple** enable-keys exist for one channel, they are combined with **AND**
(all must be enabled). When **none** of the known enable-keys are present, that
channel defaults to **enabled** (backward compatible for older documents).

Some apps store toggles only under ``users/{uid}/user-settings/{uid}`` with fields
``enableNormalCall`` (voice to the owner), ``enableCall`` (voice to the emergency
contact when no dedicated emergency flag is set), ``enableEmergencyCall`` /
``enableEmergencyVoiceCall`` (optional explicit emergency voice), ``enablePushNotification``,
``enableSms`` (see ``scanner_user_app_prefs_from_merged``).

Some apps store **disabled** flags (``…Disabled: true``) or a single map
(``scannerChannelSettings``); those are applied in ``scanner_flags_from_merged``.

Alternate keys (subset; see ``scanner_flags_from_merged``):

- Voice / “call notifications”: ``voiceCallsEnabled``, ``scannerCallNotificationEnabled``,
  ``callNotificationsEnabled``
- SMS: ``smsEnabled``
- Emergency path: ``emergencyContactEnabled``
- Emergency voice only: ``emergencyCallsEnabled``, ``scannerEmergencyVoiceCallEnabled``
- Push: ``pushNotificationsEnabled``, ``scannerPushEnabled``

Daily time windows (optional; missing or invalid = no time restriction)
-----------------------------------------------------------------------
**Enable window** (optional): while local time is *outside* this range, the channel
is off — buttons are not shown and the API rejects. Maps use 24-hour local times:

- scannerVoiceCallSchedule — voice call (owner + emergency dial)
- scannerSmsSchedule — SMS (owner + emergency SMS)
- scannerEmergencyContactSchedule — whole emergency path
- scannerPushNotificationSchedule — push (QR scanner page)

**Disable / quiet hours** (optional): while local time is *inside* this range, the
channel is off (same as above). Use this when the owner thinks in terms of “do not
disturb” hours. If both enable and disable are set, both rules apply (must be in
enable and not in disable).

- scannerVoiceCallDisableSchedule
- scannerSmsDisableSchedule
- scannerEmergencyContactDisableSchedule
- scannerPushNotificationDisableSchedule

Each schedule is a map: { "start": "HH:MM", "end": "HH:MM" } (24-hour, local).
Aliases: "from" / "to" are accepted instead of start/end.

Timezone for interpreting HH:MM (IANA name), default Asia/Kolkata:
- scannerContactTimezone (preferred) or timezone on the user document.

Overnight windows are supported (e.g. start 22:00, end 06:00).
If start and end parse to the same minute, the window is treated as empty (never on).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def coerced_true(value, *, default=True):
    """Missing → default True; only explicit false-like values disable the feature."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in ('false', '0', 'no', 'off', 'disabled'):
        return False
    if s in ('true', '1', 'yes', 'on', 'enabled'):
        return True
    return default


def _get_ci(d, key):
    """Case-insensitive get for string keys (Firestore / Dart casing varies)."""
    if not isinstance(d, dict) or key is None:
        return None
    if key in d:
        return d.get(key)
    if not isinstance(key, str):
        return None
    lk = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lk:
            return v
    return None


def _enabled_from_present_keys(user_dict, keys, *, default=True):
    """
    If none of `keys` are present (or only null values), return `default`.
    If one or more are present, every present key must coerce to True (AND).
    """
    if not isinstance(user_dict, dict):
        user_dict = {}
    present = [k for k in keys if _get_ci(user_dict, k) is not None]
    if not present:
        return default
    return all(coerced_true(_get_ci(user_dict, k), default=default) for k in present)


_NESTED_SETTINGS_KEYS = (
    # Primary paths seen on ``users/{uid}`` (camelCase, snake_case, typos)
    'userSettings',
    'UserSettings',
    'user_settings',
    'user-settings',
    'usersettings',
    'user settings',  # rare but valid if the client used a spaced field name
    'settings',
    'userSetting',
    'user_setting',
    'notificationSettings',
    'notification_settings',
    'notifications',
    'scannerSettings',
    'scanner_settings',
    'scanner_contact_prefs',
    'contactPreferences',
    'contact_preferences',
    'preferences',
    'appSettings',
    'app_settings',
    'user_preferences',
    'accountSettings',
    'account_settings',
    'ownerSettings',
    'owner_settings',
    'private',
    'privateData',
    'private_data',
)


_MERGEONE_CHILD_KEYS = frozenset(
    {
        'scannerPrefs',
        'scanner_prefs',
        'notificationPreferences',
        'notification_preferences',
        'pref',
        'prefs',
        'channels',
        'channelSettings',
        'channel_settings',
        'contactPrefs',
        'contact_prefs',
    }
)


def _is_scalar_pref_value(v):
    """Avoid treating arbitrary strings (e.g. model names) as booleans."""
    if isinstance(v, (bool, int, float)):
        return True
    if isinstance(v, str):
        sl = v.strip().lower()
        return sl in (
            'true',
            'false',
            '0',
            '1',
            'yes',
            'no',
            'on',
            'off',
            'enabled',
            'disabled',
        )
    return False


def _is_scanner_prefs_leaf_key(kl: str) -> bool:
    if kl.startswith('scanner'):
        return True
    if kl in (
        'voicecallsenabled',
        'smsenabled',
        'pushenabled',
        'pushnotificationsenabled',
        'callnotificationsenabled',
        'callnotificationenabled',
        'emergencycontactenabled',
        'emergencycallsenabled',
        'enablecall',
        'enablenormalcall',
        'enablepushnotification',
        'enablesms',
        'enablechat',
        'enableemergencycall',
        'enableemergencyvoicecall',
        'enableemergencysms',
        'voice',
        'sms',
        'push',
        'calls',
        'call',
        'phone',
        'fcm',
        'notification',
        'emergency',
        'emergencycontact',
        'emergencycall',
        'emergencyvoice',
    ):
        return True
    if (kl.endswith('enabled') or kl.endswith('disabled')) and any(
        x in kl
        for x in (
            'voice',
            'sms',
            'push',
            'call',
            'emergency',
            'notification',
            'scanner',
        )
    ):
        return True
    return False


def _deep_merge_scanner_leaves(source, merged, depth=0, max_depth=28):
    """
    Pull scanner / channel booleans from arbitrarily nested maps (e.g. userSettings
    → notifications → … → scannerVoiceCallEnabled) into the flat merge dict.
    """
    if not isinstance(source, dict) or depth > max_depth:
        return
    for k, v in source.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, dict):
            _deep_merge_scanner_leaves(v, merged, depth + 1, max_depth)
            continue
        if v is None:
            continue
        kl = k.lower()
        if _is_scanner_prefs_leaf_key(kl) and _is_scalar_pref_value(v):
            merged[k] = v


def merge_user_scanner_subdocuments(db, user_ref, user_data):
    """
    Merge scanner-related settings for this **user id** (the Firestore document id
    of ``users/{uid}``, i.e. the vehicle owner's ``ownerId``).

    Sources merged (later wins on duplicate keys):

    1. Top-level collections keyed by uid, e.g. ``userSettings/{uid}`` (common when
       the app does *not* nest settings under ``users/{uid}``).
    2. Subcollections under ``users/{uid}/…``, e.g. ``userSettings/default``.
    """
    out = dict(user_data) if isinstance(user_data, dict) else {}
    if db is None or user_ref is None:
        return out
    uid = str(user_ref.id).strip() if getattr(user_ref, 'id', None) else ''
    if uid:
        # Root collections: ``{collection}/{userId}`` (same uid as ``users/{uid}``)
        for coll in (
            'userSettings',
            'UserSettings',
            'user_settings',
            'user-settings',
            'UserPreferences',
            'user_preferences',
        ):
            try:
                snap = db.collection(coll).document(uid).get()
                if snap.exists:
                    doc = snap.to_dict() or {}
                    if isinstance(doc, dict):
                        out.update(doc)
            except Exception:
                continue

    paths = (
        ('userSettings', 'default'),
        ('userSettings', 'data'),
        ('userSettings', 'preferences'),
        # Doc id = same uid as parent user (some SDKs use this instead of "default")
        ('userSettings', uid),
        ('user_settings', 'default'),
        ('user_settings', uid),
        # Flutter / mobile path: users/{uid}/user-settings/{uid}
        ('user-settings', uid),
        ('user-settings', 'default'),
        ('settings', 'default'),
        ('settings', 'app'),
        ('settings', uid),
        ('app_settings', 'default'),
        ('preferences', 'default'),
        ('private', 'settings'),
        ('config', 'scanner'),
        ('notification_settings', 'default'),
        ('notifications', 'settings'),
    )
    for coll, doc_id in paths:
        if not coll or not doc_id:
            continue
        try:
            snap = user_ref.collection(coll).document(doc_id).get()
            if snap.exists:
                sub = snap.to_dict() or {}
                if isinstance(sub, dict):
                    out.update(sub)
        except Exception:
            continue
    return out


def merge_vehicle_scanner_subdocuments(db, vehicle_ref, vehicle_data):
    out = dict(vehicle_data) if isinstance(vehicle_data, dict) else {}
    if db is None or vehicle_ref is None:
        return out
    paths = (
        ('settings', 'default'),
        ('vehicleSettings', 'default'),
        ('scannerSettings', 'default'),
    )
    for coll, doc_id in paths:
        try:
            snap = vehicle_ref.collection(coll).document(doc_id).get()
            if snap.exists:
                sub = snap.to_dict() or {}
                if isinstance(sub, dict):
                    out.update(sub)
        except Exception:
            continue
    return out


def scanner_user_app_prefs_from_merged(merged):
    """
    App-level booleans from ``users/{uid}/user-settings/{uid}`` (flattened into ``merged``).

    **Owner (contact owner / normal voice)**
    - Voice to the owner’s number: ``enableNormalCall`` only (Firestore meaning for
      “contact owner” calls).

    **Emergency (voice to emergency number)**
    - If ``enableEmergencyCall`` or ``enableEmergencyVoiceCall`` is present, that
      value controls emergency voice.
    - If neither is present, ``enableCall`` is used (in this schema it means
      emergency voice, not owner calls).
    - SMS: ``enableEmergencySms`` — if absent, falls back to ``enableSms``.

    **Push:** ``enablePushNotification``

    Missing keys default to **true** so older documents without this subdoc behave as before.
    """
    if not isinstance(merged, dict):
        merged = {}
    enable_call = coerced_true(_get_ci(merged, 'enableCall'), default=True)
    enable_normal_call = coerced_true(_get_ci(merged, 'enableNormalCall'), default=True)
    enable_push = coerced_true(_get_ci(merged, 'enablePushNotification'), default=True)
    enable_sms = coerced_true(_get_ci(merged, 'enableSms'), default=True)

    emergency_call_raw = _get_ci(merged, 'enableEmergencyCall')
    if emergency_call_raw is None:
        emergency_call_raw = _get_ci(merged, 'enableEmergencyVoiceCall')
    if emergency_call_raw is not None:
        emergency_call_allowed = coerced_true(emergency_call_raw, default=True)
    else:
        # enableCall = emergency voice when dedicated emergency keys are absent.
        emergency_call_allowed = enable_call

    emergency_sms_raw = _get_ci(merged, 'enableEmergencySms')
    if emergency_sms_raw is None:
        emergency_sms_raw = _get_ci(merged, 'enableEmergencySMS')
    emergency_sms_allowed = (
        coerced_true(emergency_sms_raw, default=True)
        if emergency_sms_raw is not None
        else enable_sms
    )

    return {
        'owner_call_allowed': enable_normal_call,
        'emergency_call_allowed': emergency_call_allowed,
        'push_allowed': enable_push,
        'owner_sms_allowed': enable_sms,
        'emergency_sms_allowed': emergency_sms_allowed,
        # Backward compatibility for callers expecting a single SMS gate
        'sms_allowed': enable_sms,
    }


def scanner_pref_merged_dict(user_dict, vehicle_dict=None):
    """
    Flatten nested settings maps and merge user + vehicle (vehicle wins on conflicts).

    Many clients store QR/scanner toggles only under ``users/{uid}.userSettings``
    (or ``user_settings``, ``UserSettings``, etc.) or on ``vehicles/{id}``; reading
    only top-level user fields misses ``false`` values.
    """
    merged = {}

    def _absorb(doc):
        if not isinstance(doc, dict):
            return
        for nk in _NESTED_SETTINGS_KEYS:
            sub = _get_ci(doc, nk)
            if isinstance(sub, dict):
                merged.update(sub)
                for ck in _MERGEONE_CHILD_KEYS:
                    inner = _get_ci(sub, ck)
                    if isinstance(inner, dict):
                        merged.update(inner)
        merged.update(doc)

    _absorb(user_dict)
    _absorb(vehicle_dict)
    _deep_merge_scanner_leaves(user_dict, merged)
    _deep_merge_scanner_leaves(vehicle_dict, merged)
    return merged


def _overlay_channel_setting_blobs(merged, flags):
    """Short maps like scannerChannelSettings: { voice: false, sms: true }."""
    out = dict(flags)
    if not isinstance(merged, dict):
        return out
    blob_keys = (
        'scannerChannelSettings',
        'contactChannels',
        'qrScannerChannels',
        'scanner_channels',
        'scannerChannels',
    )
    channel_aliases = (
        ('voice', ('voice', 'voiceCall', 'voiceCalls', 'calls', 'call', 'phone', 'callEnabled')),
        ('sms', ('sms', 'smsNotification', 'text', 'textMessage')),
        ('push', ('push', 'fcm', 'pushNotification', 'appNotification', 'notification')),
        (
            'emergency',
            ('emergency', 'emergencyContact', 'emergencyPath', 'emergency_contact'),
        ),
        (
            'emergency_voice',
            ('emergencyCall', 'emergencyVoice', 'emergencyCalls', 'emergency_call'),
        ),
    )
    for blob_key in blob_keys:
        blob = _get_ci(merged, blob_key)
        if not isinstance(blob, dict):
            continue
        for eff_key, aliases in channel_aliases:
            picked = None
            for a in aliases:
                raw = _get_ci(blob, a)
                if raw is not None:
                    picked = coerced_true(raw, default=True)
                    break
            if picked is not None:
                out[eff_key] = out[eff_key] and picked
    return out


def _apply_disabled_flags(merged, flags):
    """When *Disabled is explicitly true, force that channel off."""
    if not isinstance(merged, dict):
        return flags
    out = dict(flags)

    def _off_if_true(*keys):
        for k in keys:
            raw = _get_ci(merged, k)
            if raw is not None:
                if coerced_true(raw, default=False):
                    return False
        return None

    pairs = [
        (
            'voice',
            (
                'scannerVoiceCallDisabled',
                'voiceCallsDisabled',
                'disableVoiceCall',
                'callNotificationsDisabled',
                'scannerCallNotificationsDisabled',
            ),
        ),
        ('sms', ('scannerSmsDisabled', 'smsDisabled', 'smsNotificationsDisabled')),
        (
            'push',
            (
                'scannerPushNotificationDisabled',
                'pushNotificationsDisabled',
                'scannerPushDisabled',
            ),
        ),
        (
            'emergency',
            (
                'scannerEmergencyContactDisabled',
                'emergencyContactDisabled',
                'emergencyDisabled',
            ),
        ),
        (
            'emergency_voice',
            (
                'scannerEmergencyCallDisabled',
                'emergencyCallsDisabled',
                'emergencyVoiceCallDisabled',
            ),
        ),
    ]
    for eff_key, dkeys in pairs:
        hit = _off_if_true(*dkeys)
        if hit is False:
            out[eff_key] = False
    return out


def scanner_flags_from_merged(merged):
    """Resolve scanner channel booleans from a flat merged user+vehicle map."""
    if not isinstance(merged, dict):
        merged = {}
    flags = {
        'voice': _enabled_from_present_keys(
            merged,
            (
                'scannerVoiceCallEnabled',
                'voiceCallsEnabled',
                'scannerVoiceCallsEnabled',
                'scannerCallNotificationEnabled',
                'callNotificationsEnabled',
                'callNotificationEnabled',
                'scanner_voice_call_enabled',
                'voice_call_enabled',
                'isVoiceCallEnabled',
            ),
            default=True,
        ),
        'sms': _enabled_from_present_keys(
            merged,
            (
                'scannerSmsEnabled',
                'smsEnabled',
                'smsNotificationsEnabled',
                'scanner_sms_enabled',
                'isSmsEnabled',
            ),
            default=True,
        ),
        'emergency': _enabled_from_present_keys(
            merged,
            (
                'scannerEmergencyContactEnabled',
                'emergencyContactEnabled',
                'scanner_emergency_contact_enabled',
                'isEmergencyContactEnabled',
            ),
            default=True,
        ),
        'push': _enabled_from_present_keys(
            merged,
            (
                'scannerPushNotificationEnabled',
                'pushNotificationsEnabled',
                'scannerPushEnabled',
                'scannerPushNotificationsEnabled',
                'scanner_push_notification_enabled',
                'isPushNotificationEnabled',
                'pushEnabled',
            ),
            default=True,
        ),
        'emergency_voice': _enabled_from_present_keys(
            merged,
            (
                'scannerEmergencyCallEnabled',
                'emergencyCallsEnabled',
                'scannerEmergencyVoiceCallEnabled',
                'scanner_emergency_call_enabled',
                'isEmergencyCallEnabled',
            ),
            default=True,
        ),
    }
    flags = _overlay_channel_setting_blobs(merged, flags)
    flags = _apply_disabled_flags(merged, flags)
    return flags


def scanner_flags_from_user_doc(user_dict, vehicle_dict=None):
    return scanner_flags_from_merged(
        scanner_pref_merged_dict(user_dict, vehicle_dict)
    )


def _tz_for_user(user_dict):
    if not isinstance(user_dict, dict):
        user_dict = {}
    z = _get_ci(user_dict, 'scannerContactTimezone') or _get_ci(user_dict, 'timezone')
    if isinstance(z, str) and z.strip():
        try:
            return ZoneInfo(z.strip())
        except Exception:
            pass
    return ZoneInfo('Asia/Kolkata')


def _parse_hh_mm(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace('.', ':')
    if ':' not in s:
        if s.isdigit() and len(s) <= 2:
            h = int(s)
            return (h, 0) if 0 <= h <= 23 else None
        return None
    parts = s.split(':')
    try:
        hi = int(parts[0])
        mi = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hi <= 23 and 0 <= mi <= 59:
            return hi, mi
    except (ValueError, IndexError):
        pass
    return None


def _to_minutes(tup):
    return tup[0] * 60 + tup[1]


def is_within_daily_window(schedule, tz):
    """
    True if there is no effective schedule restriction, or if local "now" is inside the window.
    """
    if schedule is None:
        return True
    if not isinstance(schedule, dict):
        return True
    start_raw = schedule.get('start')
    if start_raw in (None, ''):
        start_raw = schedule.get('from')
    end_raw = schedule.get('end')
    if end_raw in (None, ''):
        end_raw = schedule.get('to')
    st = _parse_hh_mm(start_raw)
    et = _parse_hh_mm(end_raw)
    if st is None or et is None:
        return True

    sm = _to_minutes(st)
    em = _to_minutes(et)
    if sm == em:
        return False

    now = datetime.now(tz)
    nm = _to_minutes((now.hour, now.minute))

    if sm < em:
        return sm <= nm <= em
    return nm >= sm or nm <= em


def schedule_is_binding(schedule):
    """True if schedule is a dict with a usable start/end window (not degenerate)."""
    if schedule is None or not isinstance(schedule, dict):
        return False
    start_raw = schedule.get('start')
    if start_raw in (None, ''):
        start_raw = schedule.get('from')
    end_raw = schedule.get('end')
    if end_raw in (None, ''):
        end_raw = schedule.get('to')
    st = _parse_hh_mm(start_raw)
    et = _parse_hh_mm(end_raw)
    if st is None or et is None:
        return False
    return _to_minutes(st) != _to_minutes(et)


def _channel_allowed_by_time(user_dict, enable_key, disable_key, tz):
    """
    True if optional enable-window (if set) contains now and optional disable-window
    (if set) does not contain now.
    """
    if not isinstance(user_dict, dict):
        user_dict = {}
    en = _get_ci(user_dict, enable_key)
    dis = _get_ci(user_dict, disable_key)
    if schedule_is_binding(en):
        if not is_within_daily_window(en, tz):
            return False
    if schedule_is_binding(dis):
        if is_within_daily_window(dis, tz):
            return False
    return True


def scanner_effective_channels_now(user_dict, vehicle_dict=None):
    """
    Combine boolean flags with optional per-channel enable + disable schedules (local TZ).
    Outside allowed time, channels are hidden on the scanner page and blocked in the API.
    """
    if not isinstance(user_dict, dict):
        user_dict = {}
    merged = scanner_pref_merged_dict(user_dict, vehicle_dict)
    f = scanner_flags_from_merged(merged)
    tz = _tz_for_user(merged)
    voice = f['voice'] and _channel_allowed_by_time(
        merged,
        'scannerVoiceCallSchedule',
        'scannerVoiceCallDisableSchedule',
        tz,
    )
    sms = f['sms'] and _channel_allowed_by_time(
        merged,
        'scannerSmsSchedule',
        'scannerSmsDisableSchedule',
        tz,
    )
    emergency = f['emergency'] and _channel_allowed_by_time(
        merged,
        'scannerEmergencyContactSchedule',
        'scannerEmergencyContactDisableSchedule',
        tz,
    )
    push = f['push'] and _channel_allowed_by_time(
        merged,
        'scannerPushNotificationSchedule',
        'scannerPushNotificationDisableSchedule',
        tz,
    )
    emergency_voice = f['emergency_voice']
    return {
        'voice': voice,
        'sms': sms,
        'emergency': emergency,
        'push': push,
        'emergency_voice': emergency_voice,
    }


def normalize_phone_digits(phone_number):
    """10-digit Indian mobile or None (same rules as views.normalize_phone_number)."""
    if phone_number is None:
        return None
    digits = ''.join(c for c in str(phone_number).strip() if c.isdigit())
    if not digits:
        return None
    if len(digits) >= 12 and digits.startswith('91'):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) == 10 and digits.isdigit():
        return digits
    return None


def send_scanner_voice_call_attempt_push(db, qr_id, destination_10, caller_10):
    """
    Best-effort FCM alert to the **vehicle owner** when a scanner successfully
    registers a QR voice-bridge call (to the owner or to the emergency contact).

    Uses the owner app push toggle ``enablePushNotification`` (merged user
    settings). Scanner-page “Push” channel toggles and push quiet-hour schedules
    are **not** applied here: if a voice bridge to the owner or emergency number
    was allowed, the owner still gets a transactional heads-up when app push is
    on and an FCM token is present. Failures are logged only; they do not affect
    call registration.

    FCM ``data.notificationType`` is ``scanner_call_attempt`` with ``callTarget``
    ``owner`` | ``emergency`` for the mobile app to handle.
    """
    try:
        from .fcm_push import send_push_to_tokens
    except Exception as exc:  # pragma: no cover
        logger.warning('scanner_call_push: fcm_push unavailable: %s', exc)
        return
    if not qr_id or not isinstance(qr_id, str):
        return
    dest = ''.join(c for c in str(destination_10 or '') if c.isdigit())
    if len(dest) != 10:
        return
    try:
        qr_doc = db.collection('qrcodes').document(qr_id).get()
        if not qr_doc.exists:
            return
        qr_data = qr_doc.to_dict() or {}
        vehicle_id = qr_data.get('vehicleID')
        if not vehicle_id:
            return
        vehicle_doc = db.collection('vehicles').document(vehicle_id).get()
        if not vehicle_doc.exists:
            return
        vehicle_data = vehicle_doc.to_dict() or {}
        owner_id = vehicle_data.get('ownerId')
        if not owner_id:
            return
        user_doc = db.collection('users').document(owner_id).get()
        if not user_doc.exists:
            return
        user_data = user_doc.to_dict() or {}
        user_ref = db.collection('users').document(owner_id)
        vehicle_ref = db.collection('vehicles').document(vehicle_id)
        user_data = merge_user_scanner_subdocuments(db, user_ref, user_data)
        vehicle_data = merge_vehicle_scanner_subdocuments(db, vehicle_ref, vehicle_data)
        merged = scanner_pref_merged_dict(user_data, vehicle_data)
        app_prefs = scanner_user_app_prefs_from_merged(merged)
        if not app_prefs['push_allowed']:
            return

        vehicle_token = vehicle_data.get('fcmToken') or ''
        single_token = user_data.get('fcmToken') or ''
        tokens = []
        seen = set()
        for t in (vehicle_token, single_token):
            if isinstance(t, str) and t and t not in seen:
                seen.add(t)
                tokens.append(t)
        if not tokens:
            return

        owner_d = normalize_phone_digits(user_data.get('contactNumber', ''))
        emerg_d = normalize_phone_digits(user_data.get('defaultEmergencyContact', ''))
        if owner_d and dest == owner_d:
            call_target = 'owner'
            title = 'Someone is trying to call you'
            body = (
                'Someone scanned your SudoTag QR and is placing a voice call to your '
                'registered mobile number.'
            )
        elif emerg_d and dest == emerg_d:
            call_target = 'emergency'
            title = 'Someone is calling your emergency number'
            body = (
                'Someone scanned your SudoTag QR and is placing a voice call to the '
                'emergency contact on this vehicle.'
            )
        else:
            call_target = 'unknown'
            title = 'Someone started a voice call via your QR'
            body = (
                'Someone scanned your SudoTag QR and started a voice call through '
                'SudoTag.'
            )

        cd = ''.join(c for c in str(caller_10 or '') if c.isdigit())
        if len(cd) >= 12 and cd.startswith('91'):
            cd = cd[2:]
        if len(cd) == 11 and cd.startswith('0'):
            cd = cd[1:]
        if len(cd) >= 4:
            body = f'{body} Caller number ends in {cd[-4:]}.'

        fcm_data = {
            'vehicleId': str(vehicle_id),
            'qrId': str(qr_id),
            'notificationType': 'incoming_call',
            'type': 'incoming_call',
            'callTarget': call_target,
        }

        push_result = send_push_to_tokens(
            db,
            user_id=str(owner_id),
            tokens=tokens,
            title=title,
            body=body,
            data=fcm_data,
            store_inbox=True,
        )
        if not push_result.get('success'):
            logger.warning(
                'scanner_call_push FCM failed: %s',
                push_result.get('last_error') or push_result.get('error'),
            )
    except Exception as exc:
        logger.warning('scanner_call_push failed: %s', exc)


def validate_scanner_call_for_qr(db, qr_id, destination_10):
    """
    Returns None if the call may proceed, else a short user-facing error string.
    """
    if not qr_id or not isinstance(qr_id, str):
        return 'Missing QR reference.'
    dest = ''.join(c for c in str(destination_10 or '') if c.isdigit())
    if len(dest) != 10:
        return 'Invalid destination.'
    try:
        qr_doc = db.collection('qrcodes').document(qr_id).get()
    except Exception:
        return 'Lookup failed.'
    if not qr_doc.exists:
        return 'QR code not found.'
    qr_data = qr_doc.to_dict() or {}
    if not qr_data.get('isAssigned'):
        return 'QR code is not assigned.'
    vehicle_id = qr_data.get('vehicleID')
    if not vehicle_id:
        return 'Vehicle not linked.'
    vehicle_doc = db.collection('vehicles').document(vehicle_id).get()
    if not vehicle_doc.exists:
        return 'Vehicle not found.'
    vehicle_data = vehicle_doc.to_dict() or {}
    owner_id = vehicle_data.get('ownerId')
    if not owner_id:
        return 'Owner not found.'
    user_doc = db.collection('users').document(owner_id).get()
    if not user_doc.exists:
        return 'Owner profile not found.'
    user_data = user_doc.to_dict() or {}
    user_ref = db.collection('users').document(owner_id)
    vehicle_ref = db.collection('vehicles').document(vehicle_id)
    user_data = merge_user_scanner_subdocuments(db, user_ref, user_data)
    vehicle_data = merge_vehicle_scanner_subdocuments(db, vehicle_ref, vehicle_data)
    merged = scanner_pref_merged_dict(user_data, vehicle_data)
    app_prefs = scanner_user_app_prefs_from_merged(merged)
    flags = scanner_flags_from_user_doc(user_data, vehicle_data)
    eff = scanner_effective_channels_now(user_data, vehicle_data)

    if not flags['voice']:
        return 'Voice calls are disabled for this vehicle.'
    if not eff['voice']:
        return (
            'Voice calls are not available at this time for this vehicle '
            '(owner quiet hours or outside allowed window).'
        )

    owner_d = normalize_phone_digits(user_data.get('contactNumber', ''))
    emerg_d = normalize_phone_digits(user_data.get('defaultEmergencyContact', ''))
    if owner_d and dest == owner_d:
        if not app_prefs['owner_call_allowed']:
            return 'Owner voice calls are disabled in the owner\'s app settings.'
        return None
    if emerg_d and dest == emerg_d:
        if not flags['emergency']:
            return 'Emergency calling is disabled for this vehicle.'
        if not eff['emergency']:
            return (
                'Emergency calling is not available at this time for this vehicle '
                '(owner quiet hours or outside allowed window).'
            )
        if not flags['emergency_voice']:
            return 'Emergency voice calls are disabled for this vehicle.'
        if not app_prefs['emergency_call_allowed']:
            return 'Emergency calling is disabled in the owner\'s app settings.'
        return None
    return 'This number is not authorized for this QR code.'
