"""SudoTag Fleet — Firestore helpers for admin (same schema as the mobile app)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from firebase_admin import firestore as fb_firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .family_assignment import has_active_family_assignment

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


def is_subscription_active(fleet: dict, now: Optional[datetime] = None) -> bool:
    status = str(fleet.get('subscriptionStatus') or '').strip().lower()
    if status not in ACTIVE_STATUSES:
        return False
    expires = _to_dt(fleet.get('subscriptionExpiresAt'))
    if expires is None:
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now < expires


def status_label(fleet: dict) -> str:
    """Badge text from status plus expiry, not the status string alone."""
    status = str(fleet.get('subscriptionStatus') or 'none').strip().lower() or 'none'
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
    row['statusLabel'] = status_label(row)
    expires = _to_dt(row.get('subscriptionExpiresAt'))
    row['expiresAt'] = expires
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


def list_drivers(db, fleet_id: str) -> list[dict]:
    rows = []
    for doc in db.collection('fleet_drivers').where('fleetId', '==', fleet_id).stream():
        data = doc.to_dict() or {}
        data['id'] = doc.id
        data['createdAtDt'] = _to_dt(data.get('createdAt'))
        rows.append(data)
    rows.sort(key=lambda r: r.get('createdAtDt') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def activation_update(
    plan_id: str,
    billing_cycle: str,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """
    Fields written on admin activate / extend.
    Expiry is now + 30 days (monthly) or now + 365 days (yearly).
    """
    resolved = resolve_plan(plan_id, billing_cycle)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return {
        'planId': resolved['planId'],
        'billingCycle': resolved['billingCycle'],
        'subscriptionStatus': 'active',
        'subscriptionExpiresAt': now + timedelta(days=resolved['periodDays']),
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
) -> None:
    payload = activation_update(plan_id, billing_cycle, now=now)
    payload['updatedAt'] = fb_firestore.SERVER_TIMESTAMP
    db.collection('fleets').document(fleet_id).update(payload)


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
        'subscriptionExpiresAt',
        'vehicleLimit',
        'driverLimit',
        'razorpayPaymentId',
        'razorpayOrderId',
    ])
    for row in rows:
        expires = row.get('expiresAt')
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
        if not has_active_family_assignment(data):
            continue
        rows.append({
            'id': doc.id,
            'registrationNumber': data.get('registrationNumber') or '',
            'assignedFamilyMemberName': data.get('assignedFamilyMemberName') or '',
            'assignedFamilyMemberContact': data.get('assignedFamilyMemberContact') or '',
            'assignedUntil': _to_dt(data.get('assignedUntil')),
        })
    rows.sort(key=lambda r: str(r.get('registrationNumber') or '').upper())
    return rows
