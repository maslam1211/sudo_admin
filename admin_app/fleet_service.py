"""SudoTag Fleet — Firestore helpers for admin (same schema as the mobile app)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from firebase_admin import firestore as fb_firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .family_assignment import (
    has_active_family_assignment,
    has_scheduled_family_assignment,
)

# INR display amounts. Cloud Functions charge the same figures in paise
# (starter monthly 99900, yearly 999900, and so on).
FLEET_PLANS = {
    'starter': {
        'name': 'Starter',
        'monthly': 999,
        'yearly': 9999,
        'vehicleLimit': 10,
        'driverLimit': 10,
    },
    'business': {
        'name': 'Business',
        'monthly': 2999,
        'yearly': 29999,
        'vehicleLimit': 50,
        'driverLimit': 50,
    },
    'enterprise': {
        'name': 'Enterprise',
        'monthly': 7999,
        'yearly': 79999,
        'vehicleLimit': 200,
        'driverLimit': 200,
    },
}

ACTIVE_STATUSES = ('active', 'trialing')
PLAN_IDS = tuple(FLEET_PLANS.keys())


class UnknownFleetPlan(ValueError):
    """planId is not starter, business, or enterprise."""


class FleetDateError(ValueError):
    """Start or end date for a fleet model is missing or out of order."""


class FleetProfileError(ValueError):
    """Company name, GSTIN, or city cannot be saved as entered."""


def _to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if hasattr(value, 'to_datetime'):
        try:
            dt = value.to_datetime()
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
        except Exception:
            return None
    return None


def plan_meta(plan_id: str) -> dict:
    """Known plan, or Starter when the stored id is missing or unrecognized."""
    return FLEET_PLANS.get(str(plan_id or '').strip()) or FLEET_PLANS['starter']


def resolve_plan(plan_id: str, billing_cycle: str) -> dict:
    """
    Match functions/fleet_subscriptions.js resolvePlan.
    Unknown planId is rejected. Any cycle other than yearly is monthly.
    """
    key = str(plan_id or '').strip()
    plan = FLEET_PLANS.get(key)
    if not plan:
        raise UnknownFleetPlan('Unknown fleet plan.')
    cycle = 'yearly' if billing_cycle == 'yearly' else 'monthly'
    return {
        'planId': key,
        'billingCycle': cycle,
        'name': plan['name'],
        'amountRupees': plan['yearly'] if cycle == 'yearly' else plan['monthly'],
        'vehicleLimit': plan['vehicleLimit'],
        'driverLimit': plan['driverLimit'],
        'periodDays': 365 if cycle == 'yearly' else 30,
    }


def _now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def is_subscription_scheduled(fleet: dict, now: Optional[datetime] = None) -> bool:
    """Active or trialing status, but the start date is still in the future."""
    status = str(fleet.get('subscriptionStatus') or '').strip().lower()
    if status not in ACTIVE_STATUSES:
        return False
    moment = _now(now)
    starts = _to_dt(fleet.get('subscriptionStartsAt'))
    if starts is None or moment >= starts:
        return False
    expires = _to_dt(fleet.get('subscriptionExpiresAt'))
    if expires is not None and moment >= expires:
        return False
    return True


def is_subscription_active(fleet: dict, now: Optional[datetime] = None) -> bool:
    status = str(fleet.get('subscriptionStatus') or '').strip().lower()
    if status not in ACTIVE_STATUSES:
        return False
    moment = _now(now)
    starts = _to_dt(fleet.get('subscriptionStartsAt'))
    if starts is not None and moment < starts:
        return False
    expires = _to_dt(fleet.get('subscriptionExpiresAt'))
    if expires is None:
        return True
    return moment < expires


def status_label(fleet: dict) -> str:
    """Badge text from status plus the start and end dates."""
    status = str(fleet.get('subscriptionStatus') or 'none').strip().lower() or 'none'
    if is_subscription_scheduled(fleet):
        return 'Scheduled'
    if is_subscription_active(fleet):
        return 'Trialing' if status == 'trialing' else 'Active'
    if status in ACTIVE_STATUSES:
        return 'Expired'
    if status == 'past_due':
        return 'Past due'
    if status == 'cancelled':
        return 'Cancelled'
    if status == 'pending':
        return 'Pending'
    return 'None'


def enrich_fleet(doc_id: str, data: dict) -> dict:
    row = dict(data or {})
    row['id'] = doc_id
    plan = plan_meta(str(row.get('planId') or 'starter'))
    row['planName'] = plan['name']
    row['monthlyRupees'] = plan['monthly']
    row['yearlyRupees'] = plan['yearly']
    cycle = 'yearly' if row.get('billingCycle') == 'yearly' else 'monthly'
    row['priceRupees'] = plan['yearly'] if cycle == 'yearly' else plan['monthly']
    row['isActive'] = is_subscription_active(row)
    row['isScheduled'] = is_subscription_scheduled(row)
    row['statusLabel'] = status_label(row)
    expires = _to_dt(row.get('subscriptionExpiresAt'))
    row['expiresAt'] = expires
    row['startsAt'] = _to_dt(row.get('subscriptionStartsAt'))
    created = _to_dt(row.get('createdAt'))
    row['createdAtDt'] = created
    return row


def list_fleets(db) -> list[dict]:
    rows = []
    for doc in db.collection('fleets').stream():
        rows.append(enrich_fleet(doc.id, doc.to_dict() or {}))
    rows.sort(key=lambda r: r.get('createdAtDt') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def get_fleet(db, fleet_id: str) -> Optional[dict]:
    snap = db.collection('fleets').document(fleet_id).get()
    if not snap.exists:
        return None
    return enrich_fleet(snap.id, snap.to_dict() or {})


def list_shift_logs(db, fleet_id: str, limit: int = 20) -> list[dict]:
    """Recent shift windows for this fleet. Newest start first."""
    rows = []
    for doc in db.collection('fleet_shift_logs').where('fleetId', '==', fleet_id).stream():
        data = doc.to_dict() or {}
        data['id'] = doc.id
        data['startedAtDt'] = _to_dt(data.get('startedAt'))
        data['endsAtDt'] = _to_dt(data.get('endsAt'))
        data['endedAtDt'] = _to_dt(data.get('endedAt'))
        rows.append(data)
    rows.sort(
        key=lambda r: r.get('startedAtDt') or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return rows[:limit]


def list_drivers(db, fleet_id: str) -> list[dict]:
    rows = []
    for doc in db.collection('fleet_drivers').where('fleetId', '==', fleet_id).stream():
        data = doc.to_dict() or {}
        data['id'] = doc.id
        data['createdAtDt'] = _to_dt(data.get('createdAt'))
        rows.append(data)
    rows.sort(key=lambda r: r.get('createdAtDt') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def _parse_date_input(raw: Any) -> Optional[datetime]:
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise FleetDateError('Use a valid start and end date.') from exc


def parse_model_window(
    start_raw: Any,
    end_raw: Any,
    *,
    billing_cycle: str,
    now: Optional[datetime] = None,
) -> dict:
    """
    Blank or today/past start → now (activate immediately).
    A future start date → 00:00 UTC that day (scheduled model).
    Blank end → start + 30 days (monthly) or 365 days (yearly).
    An end date is inclusive through 23:59:59 UTC and must be after the start.
    """
    moment = _now(now)
    cycle = 'yearly' if billing_cycle == 'yearly' else 'monthly'
    days = 365 if cycle == 'yearly' else 30
    start = _parse_date_input(start_raw)
    if start is None or start.date() <= moment.astimezone(timezone.utc).date():
        start = moment
    end = _parse_date_input(end_raw)
    if end is None:
        end = start + timedelta(days=days)
    else:
        end = end.replace(hour=23, minute=59, second=59)
    if end <= start:
        raise FleetDateError('End date must be after the start date.')
    return {
        'subscriptionStartsAt': start,
        'subscriptionExpiresAt': end,
        'scheduled': start > moment,
    }


def activation_update(
    plan_id: str,
    billing_cycle: str,
    *,
    now: Optional[datetime] = None,
    starts_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> dict:
    """
    Fields written on admin activate / extend / schedule.
    With no custom dates, expiry is now + 30 days (monthly) or now + 365 days (yearly).
    """
    resolved = resolve_plan(plan_id, billing_cycle)
    moment = _now(now)
    start = _to_dt(starts_at) or moment
    end = _to_dt(expires_at) or (start + timedelta(days=resolved['periodDays']))
    return {
        'planId': resolved['planId'],
        'billingCycle': resolved['billingCycle'],
        'subscriptionStatus': 'active',
        'subscriptionStartsAt': start,
        'subscriptionExpiresAt': end,
        'vehicleLimit': resolved['vehicleLimit'],
        'driverLimit': resolved['driverLimit'],
    }


def activate_subscription(
    db,
    fleet_id: str,
    *,
    plan_id: str,
    billing_cycle: str,
    now: Optional[datetime] = None,
    starts_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> None:
    payload = activation_update(
        plan_id,
        billing_cycle,
        now=now,
        starts_at=starts_at,
        expires_at=expires_at,
    )
    payload['updatedAt'] = fb_firestore.SERVER_TIMESTAMP
    db.collection('fleets').document(fleet_id).update(payload)


def company_update(name: str, gstin: str = '', city: str = '') -> dict:
    """Name is required. Blank GSTIN or city clears that field."""
    cleaned_name = str(name or '').strip()
    if len(cleaned_name) < 2:
        raise FleetProfileError('Enter a company name.')
    cleaned_gstin = str(gstin or '').strip().upper()
    cleaned_city = str(city or '').strip()
    return {
        'name': cleaned_name,
        'gstin': cleaned_gstin or None,
        'city': cleaned_city or None,
    }


def update_company(db, fleet_id: str, *, name: str, gstin: str = '', city: str = '') -> None:
    fields = company_update(name, gstin, city)
    db.collection('fleets').document(fleet_id).update({
        'name': fields['name'],
        'gstin': fields['gstin'] or fb_firestore.DELETE_FIELD,
        'city': fields['city'] or fb_firestore.DELETE_FIELD,
        'updatedAt': fb_firestore.SERVER_TIMESTAMP,
    })


def extension_update(fleet: dict, days: int, *, now: Optional[datetime] = None) -> dict:
    """
    Push the end date by 30 or 365 days.
    Counts from the current end date when that date is still in the future,
    otherwise from now. Plan, limits, and start date stay as they are.
    """
    if days not in (30, 365):
        raise FleetDateError('Extend by 30 or 365 days.')
    moment = _now(now)
    current = _to_dt(fleet.get('subscriptionExpiresAt')) or _to_dt(fleet.get('expiresAt'))
    base = current if current and current > moment else moment
    return {
        'subscriptionStatus': 'active',
        'subscriptionExpiresAt': base + timedelta(days=days),
    }


def extend_subscription(db, fleet_id: str, fleet: dict, days: int) -> datetime:
    payload = extension_update(fleet, days)
    payload['updatedAt'] = fb_firestore.SERVER_TIMESTAMP
    db.collection('fleets').document(fleet_id).update(payload)
    return payload['subscriptionExpiresAt']


def cancel_subscription(db, fleet_id: str) -> None:
    """Mark cancelled. The fleet document and its drivers stay."""
    db.collection('fleets').document(fleet_id).update({
        'subscriptionStatus': 'cancelled',
        'updatedAt': fb_firestore.SERVER_TIMESTAMP,
    })


def count_active_fleets(db) -> int:
    return sum(1 for fleet in list_fleets(db) if fleet.get('isActive'))


def fleets_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'fleetId',
        'name',
        'gstin',
        'city',
        'ownerId',
        'planId',
        'billingCycle',
        'priceRupees',
        'subscriptionStatus',
        'statusLabel',
        'isActive',
        'subscriptionStartsAt',
        'subscriptionExpiresAt',
        'vehicleLimit',
        'driverLimit',
        'razorpayPaymentId',
        'razorpayOrderId',
    ])
    for row in rows:
        expires = row.get('expiresAt')
        starts = row.get('startsAt')
        writer.writerow([
            row.get('id') or '',
            row.get('name') or '',
            row.get('gstin') or '',
            row.get('city') or '',
            row.get('ownerId') or '',
            row.get('planId') or '',
            row.get('billingCycle') or '',
            row.get('priceRupees') or '',
            row.get('subscriptionStatus') or '',
            row.get('statusLabel') or '',
            'yes' if row.get('isActive') else 'no',
            starts.isoformat() if starts else '',
            expires.isoformat() if expires else '',
            row.get('vehicleLimit') or '',
            row.get('driverLimit') or '',
            row.get('razorpayPaymentId') or '',
            row.get('razorpayOrderId') or '',
        ])
    return buf.getvalue()


def list_assigned_vehicles(db, owner_id: str, driver_ids: set[str]) -> list[dict]:
    """
    Vehicles whose current shift points at one of this fleet's drivers.
    Uses the same assignment fields and expiry rule as QR routing.
    """
    owner_id = str(owner_id or '').strip()
    if not owner_id or not driver_ids:
        return []
    rows = []
    query = db.collection('vehicles').where(filter=FieldFilter('ownerId', '==', owner_id))
    for doc in query.stream():
        data = doc.to_dict() or {}
        member_id = str(data.get('assignedFamilyMemberId') or '').strip()
        if member_id not in driver_ids:
            continue
        active = has_active_family_assignment(data)
        scheduled = has_scheduled_family_assignment(data)
        if not active and not scheduled:
            continue
        rows.append({
            'id': doc.id,
            'registrationNumber': data.get('registrationNumber') or '',
            'assignedFamilyMemberName': data.get('assignedFamilyMemberName') or '',
            'assignedFamilyMemberContact': data.get('assignedFamilyMemberContact') or '',
            'assignedFrom': _to_dt(data.get('assignedFrom')),
            'assignedUntil': _to_dt(data.get('assignedUntil')),
            'isScheduled': scheduled,
        })
    rows.sort(key=lambda r: str(r.get('registrationNumber') or '').upper())
    return rows
