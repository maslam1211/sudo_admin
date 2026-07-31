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
    }
