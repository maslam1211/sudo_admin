"""
Owner Live Status — mirrors Flutter OwnerLiveStatus on users/{uid}.

Canonical Firestore fields (account-level, already written by the mobile app):
  - liveStatus
  - liveStatusCustomText  (custom only)
  - liveStatusUpdatedAt

Presence (separate; do not overwrite liveStatus on disconnect):
  - isOnline
  - lastSeen
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Canonical status values (match Flutter firestoreValue).
STATUS_AVAILABLE = 'available'
STATUS_BUSY = 'busy'
STATUS_SLEEPING = 'sleeping'
STATUS_DRIVING = 'driving'
STATUS_OUT_OF_STATION = 'out_of_station'
STATUS_DO_NOT_DISTURB = 'do_not_disturb'
STATUS_CUSTOM = 'custom'

ALL_STATUSES = (
    STATUS_AVAILABLE,
    STATUS_BUSY,
    STATUS_SLEEPING,
    STATUS_DRIVING,
    STATUS_OUT_OF_STATION,
    STATUS_DO_NOT_DISTURB,
    STATUS_CUSTOM,
)

_LABELS = {
    STATUS_AVAILABLE: 'Owner Available',
    STATUS_BUSY: 'Owner Busy',
    STATUS_SLEEPING: 'Sleeping',
    STATUS_DRIVING: 'Driving',
    STATUS_OUT_OF_STATION: 'Out of Station',
    STATUS_DO_NOT_DISTURB: 'Do Not Disturb',
    STATUS_CUSTOM: 'Custom',
}

_EMOJI = {
    STATUS_AVAILABLE: '🟢',
    STATUS_BUSY: '🔴',
    STATUS_SLEEPING: '💤',
    STATUS_DRIVING: '🚗',
    STATUS_OUT_OF_STATION: '✈️',
    STATUS_DO_NOT_DISTURB: '📵',
    STATUS_CUSTOM: '✏️',
}

# Tokens for CSS / UI (plan color map + Flutter accents).
_COLOR_TOKENS = {
    STATUS_AVAILABLE: 'green',
    STATUS_BUSY: 'red',
    STATUS_SLEEPING: 'purple',
    STATUS_DRIVING: 'orange',
    STATUS_OUT_OF_STATION: 'blue',
    STATUS_DO_NOT_DISTURB: 'grey',
    STATUS_CUSTOM: 'orange',
}


def normalize_live_status(raw: Any) -> str:
    """Map Firestore / alias strings to a canonical status; unknown → available."""
    s = str(raw or '').strip().lower().replace('-', '_')
    if not s or s in ('available', 'online', 'owner_available'):
        return STATUS_AVAILABLE
    if s in ('busy', 'owner_busy'):
        return STATUS_BUSY
    if s == 'sleeping':
        return STATUS_SLEEPING
    if s == 'driving':
        return STATUS_DRIVING
    if s in ('out_of_station', 'outofstation', 'out of station'):
        return STATUS_OUT_OF_STATION
    if s in ('do_not_disturb', 'dnd', 'do not disturb'):
        return STATUS_DO_NOT_DISTURB
    if s == 'custom':
        return STATUS_CUSTOM
    return STATUS_AVAILABLE


def allows_messaging(status: str) -> bool:
    return normalize_live_status(status) != STATUS_DO_NOT_DISTURB


def allows_owner_call(status: str) -> bool:
    return normalize_live_status(status) == STATUS_AVAILABLE


def allows_emergency(status: str) -> bool:
    # Live Status never blocks emergency; prefs/schedules still apply separately.
    return True


def status_label(status: str, custom_text: str | None = None) -> str:
    st = normalize_live_status(status)
    if st == STATUS_CUSTOM:
        t = (custom_text or '').strip()
        return t if t else _LABELS[STATUS_CUSTOM]
    return _LABELS[st]


def scanner_message(status: str, custom_text: str | None = None) -> str:
    """Scanner-facing guidance shown on the Contact Owner web page."""
    st = normalize_live_status(status)
    if st == STATUS_AVAILABLE:
        return 'Owner is currently available. You can contact now.'
    if st == STATUS_DRIVING:
        return 'Owner is currently driving. Please avoid calling unless urgent.'
    if st == STATUS_BUSY:
        return 'Owner is currently busy. Please try again later.'
    if st == STATUS_SLEEPING:
        return 'Owner may be sleeping. Messaging and emergency contact only.'
    if st == STATUS_OUT_OF_STATION:
        return 'Owner is out of station. Messaging and emergency contact only.'
    if st == STATUS_DO_NOT_DISTURB:
        return 'Owner is unavailable at the moment. Emergency contact only.'
    t = (custom_text or '').strip()
    if t:
        return f'{t} — messaging and emergency contact only.'
    return 'Custom status — messaging and emergency contact only.'


def _format_updated_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    # Firestore Timestamp from Admin SDK
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, 'timestamp'):
        try:
            return datetime.utcfromtimestamp(float(value.timestamp())).isoformat() + 'Z'
        except Exception:
            pass
    s = str(value).strip()
    return s or None


def parse_owner_live_status(user_data: dict | None) -> dict:
    """
    Build a serializable Live Status view from a users/{uid} (or merged) dict.

    Returns keys used by templates, JSON poll, and readiness gating.
    """
    data = user_data if isinstance(user_data, dict) else {}
    raw_status = data.get('liveStatus')
    if raw_status is None:
        raw_status = data.get('currentStatus')
    custom = data.get('liveStatusCustomText')
    if custom is None:
        custom = data.get('statusMessage')
    custom_s = str(custom or '').strip()

    status = normalize_live_status(raw_status)
    updated_raw = data.get('liveStatusUpdatedAt')
    if updated_raw is None:
        updated_raw = data.get('statusUpdatedAt')

    is_online = data.get('isOnline')
    if is_online is None:
        is_online = False
    else:
        is_online = bool(is_online)

    last_seen = data.get('lastSeen')
    if last_seen is None:
        last_seen = data.get('lastActiveTime')

    label = status_label(status, custom_s)
    return {
        'status': status,
        'liveStatus': status,
        'label': label,
        'emoji': _EMOJI.get(status, '🟢'),
        'color': _COLOR_TOKENS.get(status, 'green'),
        'color_token': _COLOR_TOKENS.get(status, 'green'),
        'custom_text': custom_s if status == STATUS_CUSTOM else '',
        'message': scanner_message(status, custom_s),
        'scanner_message': scanner_message(status, custom_s),
        'allows_messaging': allows_messaging(status),
        'allows_owner_call': allows_owner_call(status),
        'allows_emergency': allows_emergency(status),
        'updated_at': _format_updated_at(updated_raw),
        'is_online': is_online,
        'last_seen': _format_updated_at(last_seen),
    }


def live_status_service_lines(live: dict) -> list[str]:
    """Human-readable reasons channels are paused by Live Status."""
    lines: list[str] = []
    status = live.get('status') or STATUS_AVAILABLE
    label = live.get('label') or status_label(status)
    if not live.get('allows_owner_call', True):
        lines.append(f'Owner voice calls are paused while status is {label}.')
    if not live.get('allows_messaging', True):
        lines.append(f'Messaging is paused while status is {label}.')
    return lines


def live_status_json_payload(live: dict) -> dict:
    """Compact payload for the public poll endpoint."""
    return {
        'liveStatus': live.get('status') or STATUS_AVAILABLE,
        'label': live.get('label') or 'Owner Available',
        'emoji': live.get('emoji') or '🟢',
        'color': live.get('color') or 'green',
        'message': live.get('message') or live.get('scanner_message') or '',
        'customText': live.get('custom_text') or '',
        'allowsMessaging': bool(live.get('allows_messaging', True)),
        'allowsOwnerCall': bool(live.get('allows_owner_call', True)),
        'allowsEmergency': bool(live.get('allows_emergency', True)),
        'updatedAt': live.get('updated_at'),
        'isOnline': bool(live.get('is_online', False)),
        'lastSeen': live.get('last_seen'),
    }
