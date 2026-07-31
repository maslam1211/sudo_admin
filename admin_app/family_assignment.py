"""
Family-member vehicle assignment helpers (mirror Flutter Vehicle entity).

SMS/voice use denormalized fields on ``vehicles/{id}``; expiry is evaluated at
read time and does not clear Firestore.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .scanner_contact_prefs import normalize_phone_digits


def _to_aware_datetime(value: Any) -> Optional[datetime]:
    """Convert Firestore Timestamp / datetime / epoch to aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # google.cloud.firestore Timestamp
    if hasattr(value, 'to_datetime'):
        try:
            dt = value.to_datetime()
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
        except Exception:
            pass
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def has_active_family_assignment(
    vehicle_data: Optional[Mapping[str, Any]],
    now: Optional[datetime] = None,
) -> bool:
    """
    True while a family member is actively using the vehicle
    (contact present and time window not yet expired).
    """
    if not vehicle_data:
        return False
    contact = (vehicle_data.get('assignedFamilyMemberContact') or '').strip()
    if not contact:
        return False
    until = vehicle_data.get('assignedUntil')
    if until is None:
        return True
    until_dt = _to_aware_datetime(until)
    if until_dt is None:
        # Unparseable until → treat as active (contact is set), matching
        # mobile's "null until means active" spirit for bad data.
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now < until_dt


def vehicle_owner_contact_number(
    vehicle_data: Optional[Mapping[str, Any]],
    user_data: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """
    Always the vehicle owner's 10-digit phone (never family assignment).

    Prefers ``vehicle.ownerContact``, then ``users.contactNumber``.
    """
    vehicle_data = vehicle_data or {}
    user_data = user_data or {}
    return normalize_phone_digits(
        vehicle_data.get('ownerContact') or user_data.get('contactNumber')
    )


def effective_contact_number(
    vehicle_data: Optional[Mapping[str, Any]],
    user_data: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """
    Voice/SMS destination: assigned family member while active, else owner.

    Prefers ``vehicle.ownerContact`` (mobile source of truth), falls back to
    ``users.contactNumber`` (legacy web notify path).
    """
    vehicle_data = vehicle_data or {}
    user_data = user_data or {}
    if has_active_family_assignment(vehicle_data, now=now):
        return normalize_phone_digits(
            vehicle_data.get('assignedFamilyMemberContact')
        )
    return normalize_phone_digits(
        vehicle_data.get('ownerContact') or user_data.get('contactNumber')
    )


def effective_contact_display_name(
    vehicle_data: Optional[Mapping[str, Any]],
    user_data: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> str:
    """Display name for the effective SMS/voice contact."""
    vehicle_data = vehicle_data or {}
    user_data = user_data or {}
    if has_active_family_assignment(vehicle_data, now=now):
        name = (vehicle_data.get('assignedFamilyMemberName') or '').strip()
        return name or 'Family member'
    return (
        (vehicle_data.get('ownerFullName') or '').strip()
        or (user_data.get('fullName') or '').strip()
        or 'vehicle owner'
    )
