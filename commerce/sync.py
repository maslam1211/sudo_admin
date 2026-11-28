"""Keep PostgreSQL and Firestore in step while both are in use.

import_*   Firestore -> PostgreSQL for records Firestore still masters (old app
           builds, website, admin panel edits). Never overwrites a row that
           PostgreSQL masters.
project_*  PostgreSQL -> Firestore for records the API masters, so the partner
           commission trigger, the admin panel and old builds see them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.utils import timezone as dj_tz

from api.mirror import decode, encode

from .models import (
    MASTER_FIRESTORE, MASTER_POSTGRES, CheckoutSettings, Coupon, Order, Payment, PaymentClaim,
)
from .pricing import normalize_coupon_code, parse_expires_at

logger = logging.getLogger(__name__)

SETTINGS_COLLECTION = 'web_checkout_settings'
COUPONS_COLLECTION = 'web_coupons'
ORDERS_COLLECTION = 'orders'
PAYMENTS_COLLECTION = 'payments'
CLAIMS_COLLECTION = 'payment_claims'


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


# ─── settings ────────────────────────────────────────────────────────────────
def import_settings(db, doc_id: str = 'default') -> CheckoutSettings | None:
    snap = db.collection(SETTINGS_COLLECTION).document(doc_id).get()
    if not snap.exists:
        return None
    row, _ = CheckoutSettings.objects.update_or_create(
        id=doc_id, defaults={'document': encode(snap.to_dict() or {}), 'master': MASTER_FIRESTORE,
                             'synced_at': dj_tz.now()})
    return row


def import_all_settings(db) -> int:
    count = 0
    for snap in db.collection(SETTINGS_COLLECTION).stream():
        CheckoutSettings.objects.update_or_create(
            id=snap.id, defaults={'document': encode(snap.to_dict() or {}), 'master': MASTER_FIRESTORE,
                                  'synced_at': dj_tz.now()})
        count += 1
    return count


# ─── coupons ─────────────────────────────────────────────────────────────────
def _coupon_defaults(code: str, data: dict) -> dict:
    return {
        'active': data.get('active') is True,
        'discount_type': str(data.get('discountType') or '')[:16],
        'discount_value': _num(data.get('discountValue')),
        'min_quantity': _num(data.get('minQuantity')),
        'max_uses': _num(data.get('maxUses')),
        'used_count': _num(data.get('usedCount'), 0) or 0,
        'expires_at': parse_expires_at(data.get('expiresAt')),
        'document': encode({**data, 'code': normalize_coupon_code(data.get('code')) or code}),
        'master': MASTER_FIRESTORE,
        'synced_at': dj_tz.now(),
        'deleted_at': None,
    }


def import_coupon(db, code: str) -> Coupon | None:
    """Re-read one coupon (called right after an admin save/delete or a use)."""
    code = normalize_coupon_code(code)
    if not code:
        return None
    snap = db.collection(COUPONS_COLLECTION).document(code).get()
    if not snap.exists:
        Coupon.objects.filter(code=code).update(deleted_at=dj_tz.now(), active=False)
        return None
    row, _ = Coupon.objects.update_or_create(code=code, defaults=_coupon_defaults(code, snap.to_dict() or {}))
    return row


def import_all_coupons(db) -> dict:
    seen = set()
    for snap in db.collection(COUPONS_COLLECTION).stream():
        code = normalize_coupon_code(snap.id)[:32]
        seen.add(code)
        Coupon.objects.update_or_create(code=code, defaults=_coupon_defaults(code, snap.to_dict() or {}))
    gone = Coupon.objects.filter(deleted_at__isnull=True).exclude(code__in=seen)
    return {'coupons': len(seen), 'deleted': gone.update(deleted_at=dj_tz.now(), active=False)}


# ─── orders ──────────────────────────────────────────────────────────────────
def order_columns(data: dict) -> dict:
    """Typed columns derived from a Firestore-shaped order document."""
    return {
        'user_id': str(data.get('userId') or '')[:128],
        'payment_status': str(data.get('paymentStatus') or '')[:32],
        'payment_verified': data.get('paymentVerified') is True,
        'order_status': _int(data.get('orderStatus'), 0),
        'razorpay_order_id': str(data.get('paymentOrderId') or '')[:64],
        'razorpay_payment_id': str(data.get('paymentId') or '')[:64],
        'amount': _num(data.get('amount'), 0) or 0,
        'quantity': max(1, _int(data.get('quantity'), 1)),
        'selected_item': str(data.get('selectedItem') or '')[:64],
        'coupon_code': str(data.get('couponCode') or '')[:32],
        'partner_code': str(data.get('partnerCode') or '')[:64],
        'qr_id': str(data.get('qrId') or '')[:128],
        'source': str(data.get('source') or data.get('channel') or '')[:32],
        'placed_at': _dt(data.get('timestamp')),
    }


def import_orders(db) -> dict:
    """Import every Firestore order PostgreSQL doesn't master. Rows that
    disappeared from Firestore are kept, marked deleted."""
    stats = {'imported': 0, 'skipped_postgres_master': 0, 'marked_deleted': 0}
    postgres_owned = set(Order.objects.filter(master=MASTER_POSTGRES).values_list('id', flat=True))
    seen = set()
    for snap in db.collection(ORDERS_COLLECTION).stream():
        seen.add(snap.id)
        if snap.id in postgres_owned:
            stats['skipped_postgres_master'] += 1
            continue
        data = snap.to_dict() or {}
        Order.objects.update_or_create(id=snap.id, defaults={
            **order_columns(data), 'document': encode(data), 'master': MASTER_FIRESTORE,
            'synced_at': dj_tz.now(), 'deleted_at': None,
        })
        stats['imported'] += 1
    gone = Order.objects.filter(master=MASTER_FIRESTORE, deleted_at__isnull=True).exclude(id__in=seen)
    stats['marked_deleted'] = gone.update(deleted_at=dj_tz.now())
    return stats


def import_order(db, order_id: str) -> Order | None:
    snap = db.collection(ORDERS_COLLECTION).document(order_id).get()
    existing = Order.objects.filter(id=order_id).first()
    if existing and existing.master == MASTER_POSTGRES:
        return existing
    if not snap.exists:
        if existing:
            existing.deleted_at = dj_tz.now()
            existing.save(update_fields=['deleted_at'])
        return existing
    data = snap.to_dict() or {}
    row, _ = Order.objects.update_or_create(id=order_id, defaults={
        **order_columns(data), 'document': encode(data), 'master': MASTER_FIRESTORE,
        'synced_at': dj_tz.now(), 'deleted_at': None,
    })
    return row


def project_order(db, order: Order) -> bool:
    """Write a PostgreSQL-mastered order to Firestore. Failures are retried
    by the worker (rows with projected_at older than updated_at)."""
    if order.master != MASTER_POSTGRES:
        return False
    try:
        ref = db.collection(ORDERS_COLLECTION).document(order.id)
        if order.deleted_at:
            ref.delete()
        else:
            ref.set(decode(order.document), merge=True)
        Order.objects.filter(pk=order.pk).update(projected_at=dj_tz.now())
        return True
    except Exception:
        logger.exception('Projecting order %s to Firestore failed (will retry)', order.id)
        return False


def project_pending_orders(db) -> int:
    from django.db.models import F, Q

    pending = Order.objects.filter(master=MASTER_POSTGRES).filter(
        Q(projected_at__isnull=True) | Q(projected_at__lt=F('updated_at')))
    return sum(1 for order in pending[:200] if project_order(db, order))


# ─── payments and claims ─────────────────────────────────────────────────────
def import_payments(db) -> int:
    count = 0
    for snap in db.collection(PAYMENTS_COLLECTION).stream():
        if Payment.objects.filter(id=snap.id, master=MASTER_POSTGRES).exists():
            continue
        data = snap.to_dict() or {}
        amount = data.get('amount')
        Payment.objects.update_or_create(id=snap.id, defaults={
            'razorpay_payment_id': str(data.get('paymentId') or snap.id)[:64],
            'razorpay_order_id': str(data.get('orderId') or '')[:64],
            'order_id': str(data.get('firestoreOrderId') or '')[:128],
            'user_id': str(data.get('userId') or '')[:128],
            'amount_paise': _int(amount) if amount is not None else None,
            'verified': data.get('verified') is True,
            'verification_method': str(data.get('verificationMethod') or '')[:16],
            'document': encode(data), 'master': MASTER_FIRESTORE, 'synced_at': dj_tz.now(),
        })
        count += 1
    return count


def import_claims(db) -> int:
    count = 0
    for snap in db.collection(CLAIMS_COLLECTION).stream():
        data = snap.to_dict() or {}
        _, created = PaymentClaim.objects.get_or_create(payment_id=snap.id, defaults={
            'purpose': str(data.get('purpose') or '')[:160], 'uid': str(data.get('uid') or '')[:128],
            'claimed_at': _dt(data.get('claimedAt')) or dj_tz.now(), 'master': MASTER_FIRESTORE,
        })
        count += int(created)
    return count


def import_everything(db) -> dict:
    """One pass of every checkout collection (worker job + backfill)."""
    return {
        'settings': import_all_settings(db),
        'coupons': import_all_coupons(db),
        'orders': import_orders(db),
        'payments': import_payments(db),
        'claims': import_claims(db),
        'projected': project_pending_orders(db),
    }
