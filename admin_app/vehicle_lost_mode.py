"""
Vehicle Lost Mode — mirrors Flutter Vehicle.isLostMode on vehicles/{id}.

Canonical Firestore fields (per-vehicle, written by the mobile app):
  - isLostMode          bool
  - lostModeEnabledAt   Timestamp | null  (set on enable, cleared on disable)

Lost Mode does not gate SMS / push / call / emergency channels — Live Status
and scanner prefs still do. This helper only drives scanner recovery copy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

BANNER_TITLE = 'Vehicle reported missing'
BANNER_BODY = (
    'The owner has enabled Lost Mode. If you see this vehicle, please notify '
    'them — your tip can help with recovery.'
)
BADGE_LABEL = 'REPORTED MISSING'
TIP_REASON = 'I spotted this vehicle'
TIP_CTA_TITLE = 'Tip owner — I spotted this vehicle'
TIP_CTA_SUB = 'Send a tip to help recover this vehicle'
REASONS_HEADING = 'Help recover this vehicle'
REASONS_LEAD = 'Tip the owner — choose how you spotted this vehicle, or pick another reason.'

# Automatic push when a Lost Mode vehicle QR is opened in the browser.
AUTO_PUSH_TITLE = 'Lost Mode — Vehicle spotted'
AUTO_PUSH_BODY = (
    'Someone scanned your SUDO Tag. Your vehicle was spotted while Lost Mode is on.'
)
AUTO_PUSH_SENT_NOTICE = (
    'Owner notified automatically on their phone — thank you for helping.'
)


def _truthy_bool(raw: Any) -> bool:
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    if isinstance(raw, (int, float)):
        return raw == 1
    if isinstance(raw, str):
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(raw)


def _format_enabled_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
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


def parse_vehicle_lost_mode(vehicle_data: dict | None) -> dict:
    """
    Build a template-safe Lost Mode view from a vehicles/{id} dict.

    Always returns display strings so templates can branch on is_lost_mode only.
    """
    data = vehicle_data if isinstance(vehicle_data, dict) else {}
    is_lost = _truthy_bool(data.get('isLostMode'))
    enabled_at = _format_enabled_at(data.get('lostModeEnabledAt')) if is_lost else None
    return {
        'is_lost_mode': is_lost,
        'isLostMode': is_lost,
        'lost_mode_enabled_at': enabled_at,
        'lostModeEnabledAt': enabled_at,
        'banner_title': BANNER_TITLE,
        'banner_body': BANNER_BODY,
        'badge_label': BADGE_LABEL,
        'tip_reason': TIP_REASON,
        'tip_cta_title': TIP_CTA_TITLE,
        'tip_cta_sub': TIP_CTA_SUB,
        'reasons_heading': REASONS_HEADING,
        'reasons_lead': REASONS_LEAD,
        'auto_push_sent_notice': AUTO_PUSH_SENT_NOTICE,
    }


def collect_owner_fcm_tokens(vehicle_data: dict | None, user_data: dict | None) -> list[str]:
    """Vehicle fcmToken first, then users/{uid}.fcmToken (same as manual push)."""
    vehicle = vehicle_data if isinstance(vehicle_data, dict) else {}
    user = user_data if isinstance(user_data, dict) else {}
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in (vehicle.get('fcmToken'), user.get('fcmToken')):
        if isinstance(raw, str) and raw.strip() and raw.strip() not in seen:
            seen.add(raw.strip())
            tokens.append(raw.strip())
    return tokens


def attempt_lost_mode_auto_push(
    *,
    request,
    db,
    qr_id: str,
    vehicle_id: str,
    vehicle_data: dict | None,
    user_data: dict | None,
    user_ref,
    vehicle_ref,
    push_capable: bool,
    send_push_fn,
) -> dict:
    """
    On Lost Mode QR page load, push the owner once per browser session.

    Uses push capability (token + prefs) but does **not** require Live Status
    messaging — recovery sightings should still reach the owner when possible.
    Reloads are deduped via session; ``?_sudo_rescan=1`` clears the flag.
    """
    from .scanner_notify_session_controls import (
        has_lost_mode_auto_push_sent,
        mark_lost_mode_auto_push_sent,
    )

    result = {
        'attempted': False,
        'sent': False,
        'skipped_reason': None,
        'notice': '',
    }
    lost = parse_vehicle_lost_mode(vehicle_data)
    if not lost['is_lost_mode']:
        result['skipped_reason'] = 'not_lost_mode'
        return result

    if has_lost_mode_auto_push_sent(request, qr_id):
        result['skipped_reason'] = 'already_sent'
        result['notice'] = AUTO_PUSH_SENT_NOTICE
        return result

    if not push_capable:
        result['skipped_reason'] = 'push_unavailable'
        return result

    tokens = collect_owner_fcm_tokens(vehicle_data, user_data)
    if not tokens:
        result['skipped_reason'] = 'no_token'
        return result

    owner_id = str((vehicle_data or {}).get('ownerId') or '')
    if not owner_id:
        result['skipped_reason'] = 'no_owner'
        return result

    result['attempted'] = True
    fcm_data = {
        'vehicleId': str(vehicle_id or ''),
        'qrId': str(qr_id or ''),
        'notificationType': 'vehicle_alert',
        'type': 'vehicle_alert',
        'lostMode': 'true',
        'lostModeSighting': 'true',
    }
    try:
        push_result = send_push_fn(
            db,
            user_id=owner_id,
            tokens=tokens,
            title=AUTO_PUSH_TITLE,
            body=AUTO_PUSH_BODY,
            data=fcm_data,
            store_inbox=True,
        )
    except Exception as exc:
        result['skipped_reason'] = 'send_failed'
        result['error'] = str(exc)
        return result

    success_count = int(push_result.get('success_count') or 0)
    failed_tokens = push_result.get('failed_tokens') or []
    vehicle_token = ''
    single_token = ''
    if isinstance(vehicle_data, dict):
        vehicle_token = vehicle_data.get('fcmToken') or ''
    if isinstance(user_data, dict):
        single_token = user_data.get('fcmToken') or ''

    if failed_tokens:
        try:
            if single_token and single_token in failed_tokens and user_ref is not None:
                user_ref.update({'fcmToken': ''})
        except Exception:
            pass
        try:
            if vehicle_token and vehicle_token in failed_tokens and vehicle_ref is not None:
                vehicle_ref.update({'fcmToken': ''})
        except Exception:
            pass

    if success_count > 0:
        mark_lost_mode_auto_push_sent(request, qr_id)
        result['sent'] = True
        result['notice'] = AUTO_PUSH_SENT_NOTICE
        result['fcm_message_id'] = push_result.get('message_id')
        return result

    result['skipped_reason'] = 'send_failed'
    result['error'] = str(push_result.get('last_error') or push_result.get('error') or 'Unknown')
    return result
