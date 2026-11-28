"""Checkout business logic (single implementation for the mobile API).

Replaces the Cloud Functions createOrder / validateCheckoutCoupon /
listCheckoutCoupons / verifyPayment and the app's own order writes. The
server now owns the whole order: price, Razorpay order, payment check and
the `paid` state. The app only collects the payment.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Callable, Optional

from django.db import transaction

from api.errors import ApiError
from api.mirror import decode, encode

from . import razorpay_guard, sync
from .models import MASTER_POSTGRES, CheckoutSettings, Coupon, Order, Payment
from .pricing import (
    active_coupon_offer, normalize_coupon_code, normalize_quantity, order_coupon_fields,
    validate_coupon_for_checkout,
)

logger = logging.getLogger(__name__)

ORDER_STATUS_PROCESSING = 1
ORDER_STATUS_DELIVERED = 3
ORDER_STATUS_CANCELLED = 4
ORDER_STATUS_FAILED = 6
NOT_CANCELLABLE = {ORDER_STATUS_DELIVERED, ORDER_STATUS_CANCELLED, ORDER_STATUS_FAILED}

ADDRESS_FIELDS = ('fullName', 'mobileNumber', 'houseNumber', 'postOffice', 'street', 'landmark',
                  'area', 'address', 'city', 'state', 'pincode', 'country')
MAX_TEXT = 200


def _now():
    return datetime.now(timezone.utc)


def paise(rupees: float) -> int:
    """JS Math.round(total * 100) — what the Cloud Function charged."""
    return int(math.floor(float(rupees) * 100 + 0.5))


# ─── settings / coupons ──────────────────────────────────────────────────────
def settings_document(db) -> dict:
    row = CheckoutSettings.objects.filter(id='default').first()
    if row is None:
        row = sync.import_settings(db)
    return decode(row.document) if row else {}


def ordering_open(settings: dict) -> bool:
    raw = settings.get('buyingOpen')
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ('false', '0', 'no')


def ordering_closed_message(settings: dict) -> str:
    return str(settings.get('buyingClosedMessage') or '').strip() or 'Out of stock'


def coupon_lookup(code: str) -> Optional[dict]:
    row = Coupon.objects.filter(code=normalize_coupon_code(code), deleted_at__isnull=True).first()
    if row is None:
        return None
    data = decode(row.document)
    data['usedCount'] = row.used_count  # includes uses recorded since the last import
    return data


def quote(db, *, coupon_code, quantity, product_key) -> dict:
    result = validate_coupon_for_checkout(
        settings=settings_document(db), coupon_lookup=coupon_lookup,
        coupon_code=coupon_code, quantity=quantity, product_key=product_key,
    )
    if not result['ok']:
        raise ApiError('invalid-argument', result['error'])
    return result['quote']


def available_offers() -> list[dict]:
    offers = []
    for row in Coupon.objects.filter(active=True, deleted_at__isnull=True).order_by('code'):
        data = decode(row.document)
        data['usedCount'] = row.used_count
        offer = active_coupon_offer(data)
        if offer:
            offers.append(offer)
    return offers


def record_coupon_use(db, code: str) -> None:
    """Same Firestore increment the Cloud Function does, then re-import."""
    from firebase_admin import firestore

    code = normalize_coupon_code(code)
    if not code:
        return
    try:
        db.collection(sync.COUPONS_COLLECTION).document(code).set(
            {'usedCount': firestore.Increment(1), 'lastUsedAt': firestore.SERVER_TIMESTAMP}, merge=True)
        sync.import_coupon(db, code)
    except Exception:
        logger.exception('Recording coupon use failed code=%s', code)


# ─── orders ──────────────────────────────────────────────────────────────────
def _text(value, limit=MAX_TEXT) -> str:
    return ' '.join(str(value or '').split())[:limit]


def _save(order: Order, document: dict, db) -> Order:
    order.document = encode(document)
    for field, value in sync.order_columns(document).items():
        setattr(order, field, value)
    order.save()
    sync.project_order(db, order)
    return order


def _owned_vehicle(db, vehicle_id: str, uid: str) -> dict:
    snap = db.collection('vehicles').document(vehicle_id).get()
    if not snap.exists or str((snap.to_dict() or {}).get('ownerId') or '') != uid:
        raise ApiError('permission-denied', 'You can only order a SudoTag for your own vehicle.')
    return snap.to_dict() or {}


def create_order(db, *, uid: str, payload: dict,
                 create_rp_order: Callable[..., dict] | None = None) -> tuple[Order, dict]:
    """Price on the server, create the Razorpay order, store and project.

    Returns (order, quote).
    """
    settings = settings_document(db)
    if not ordering_open(settings):
        raise ApiError('failed-precondition', ordering_closed_message(settings))

    vehicle_id = _text(payload.get('vehicleId'), 128)
    if not vehicle_id:
        raise ApiError('invalid-argument', 'Choose the vehicle for this SudoTag.')
    vehicle = _owned_vehicle(db, vehicle_id, uid)
    address_in = payload.get('address') if isinstance(payload.get('address'), dict) else {}
    address = {k: _text(address_in.get(k)) for k in ADDRESS_FIELDS}
    if not address['pincode'] or not (address['address'] or address['street'] or address['houseNumber']):
        raise ApiError('invalid-argument', 'Add a delivery address with a pincode.')

    product_key = _text(payload.get('selectedItem'), 64)
    priced = quote(db, coupon_code=payload.get('couponCode'), quantity=payload.get('quantity'),
                   product_key=product_key)
    amount_paise = paise(priced['total'])
    if amount_paise < 100:
        raise ApiError('invalid-argument', 'Amount must be at least ₹1.')

    create_rp_order = create_rp_order or razorpay_guard.create_order
    order_id = db.collection(sync.ORDERS_COLLECTION).document().id
    try:
        rp_order = create_rp_order(
            amount_paise=amount_paise, receipt=razorpay_guard.receipt_id(),
            notes={'userId': uid, 'orderId': order_id, 'quantity': priced['quantity'],
                   'couponCode': priced.get('code') or '', 'source': 'app-api'},
        )
    except Exception:
        logger.exception('Razorpay order creation failed for %s', order_id)
        raise ApiError('unavailable', "Couldn't start the payment. Please try again.")

    now = _now()
    document = {
        'fullName': _text(payload.get('fullName')) or address['fullName'],
        'vehicleCategory': _text(payload.get('vehicleCategory') or vehicle.get('vehicleType'), 64),
        'vehicleNumber': _text(payload.get('vehicleNumber') or vehicle.get('registrationNumber'), 32),
        'userId': uid,
        'vehicleId': vehicle_id,
        'mobile': _text(payload.get('mobile'), 20) or address['mobileNumber'],
        'selectedItem': product_key,
        'quantity': priced['quantity'],
        'qrId': _text(payload.get('qrId'), 128) or None,
        'paymentStatus': 'pending',
        'paymentOrderId': rp_order['id'],
        'paymentId': None,
        'timestamp': now,
        'orderStatus': ORDER_STATUS_PROCESSING,
        'address': address,
        **order_coupon_fields(priced),
        'source': 'app',
        'origin': 'api',
        'createdAt': now,
        'updatedAt': now,
    }
    partner_code = _text(payload.get('partnerCode'), 64).upper()
    if partner_code:
        document['partnerCode'] = partner_code  # commission rules run in the Cloud Function
    order = Order(id=order_id, master=MASTER_POSTGRES)
    return _save(order, document, db), priced


def user_orders(uid: str) -> list[Order]:
    return list(Order.objects.filter(user_id=uid, deleted_at__isnull=True).order_by('-placed_at', '-created_at'))


def _user_order(uid: str, order_id: str) -> Order:
    order = Order.objects.filter(id=order_id, user_id=uid, deleted_at__isnull=True).first()
    if order is None:
        raise ApiError('not-found', 'Order not found.')
    return order


def confirm_payment(db, *, order: Order, payment_id: str, signature: str = '', uid: str = '',
                    check=None, claim=None, verify_signature=None) -> Order:
    """Verify with Razorpay and mark paid. Idempotent for the same payment."""
    check = check or razorpay_guard.check_payment
    claim = claim or razorpay_guard.claim_payment
    verify_signature = verify_signature or razorpay_guard.signature_matches
    document = decode(order.document)
    if order.payment_verified:
        if order.razorpay_payment_id == payment_id:
            return order
        raise ApiError('already-exists', 'This order is already paid.')
    if order.master != MASTER_POSTGRES:
        raise ApiError('failed-precondition', 'Please update SudoTag to complete this order.')
    rp_order_id = order.razorpay_order_id
    expected = paise(document.get('amount') or 0)
    try:
        payment, _ = check(payment_id=payment_id, order_id=rp_order_id, expected_amount_paise=expected)
        if signature and payment.get('order_id') and not verify_signature(rp_order_id, payment_id, signature):
            raise razorpay_guard.PaymentRejected('Payment signature is invalid.')
        claim(db, payment_id=payment_id, purpose=f'order:{rp_order_id}', uid=uid or order.user_id)
    except razorpay_guard.PaymentRejected as exc:
        logger.warning('Payment %s rejected for order %s: %s', payment_id, order.id, exc.reason)
        raise ApiError('failed-precondition', exc.reason)

    now = _now()
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        document = decode(order.document)
        if order.payment_verified:
            return order
        Payment.objects.update_or_create(id=payment_id, defaults={
            'razorpay_payment_id': payment_id, 'razorpay_order_id': rp_order_id, 'order_id': order.id,
            'user_id': order.user_id, 'amount_paise': int(payment.get('amount') or expected),
            'verified': True, 'verification_method': 'signature' if signature else 'api',
            'master': MASTER_POSTGRES,
            'document': encode({'orderId': rp_order_id, 'paymentId': payment_id,
                                'amount': int(payment.get('amount') or expected), 'userId': order.user_id,
                                'verified': True, 'verifiedAt': now, 'timestamp': now,
                                'verificationMethod': 'signature' if signature else 'api',
                                'firestoreOrderId': order.id, 'source': 'app-api'}),
        })
        document.update({'paymentId': payment_id, 'paymentStatus': 'paid', 'paymentVerified': True,
                         'paymentVerifiedAt': now, 'updatedAt': now})
        coupon = document.get('couponCode')
        if coupon and not document.get('couponUsageRecorded'):
            document.update({'couponUsageRecorded': True, 'couponUsedAt': now})
        else:
            coupon = None
        order = _save(order, document, db)
    try:
        db.collection(sync.PAYMENTS_COLLECTION).document(payment_id).set(
            decode(Payment.objects.get(id=payment_id).document), merge=True)
    except Exception:
        logger.exception('Projecting payment %s failed', payment_id)
    if coupon:
        record_coupon_use(db, coupon)
    logger.info('Order %s paid (payment %s)', order.id, payment_id)
    return order


def confirm_user_payment(db, *, uid: str, order_id: str, payment_id: str, signature: str = '') -> Order:
    return confirm_payment(db, order=_user_order(uid, order_id), payment_id=payment_id,
                           signature=signature, uid=uid)


def mark_payment_failed(db, *, uid: str, order_id: str) -> Order:
    order = _user_order(uid, order_id)
    if order.payment_verified or order.master != MASTER_POSTGRES:
        return order
    document = decode(order.document)
    document.update({'paymentStatus': 'failed', 'updatedAt': _now()})
    return _save(order, document, db)


def cancel_order(db, *, uid: str, order_id: str) -> Order:
    order = _user_order(uid, order_id)
    if order.order_status in NOT_CANCELLABLE:
        raise ApiError('failed-precondition', 'This order cannot be cancelled')
    if order.master == MASTER_POSTGRES:
        document = decode(order.document)
        document.update({'orderStatus': ORDER_STATUS_CANCELLED, 'updatedAt': _now()})
        return _save(order, document, db)
    # Firestore still masters orders from older builds: change it there.
    db.collection(sync.ORDERS_COLLECTION).document(order_id).update(
        {'orderStatus': ORDER_STATUS_CANCELLED})
    return sync.import_order(db, order_id)


# ─── admin panel hooks (called after its Firestore write) ────────────────────
def admin_status_changed(db, order_id: str, new_status: int) -> None:
    order = Order.objects.filter(id=order_id).first()
    if order is None or order.master != MASTER_POSTGRES:
        sync.import_order(db, order_id)
        return
    document = decode(order.document)
    document.update({'orderStatus': int(new_status), 'updatedAt': _now()})
    _save(order, document, db)


def admin_orders_deleted(db, order_ids) -> None:
    for order in Order.objects.filter(id__in=list(order_ids)):
        order.deleted_at = _now()
        order.save(update_fields=['deleted_at', 'updated_at'])


# ─── Razorpay webhook ────────────────────────────────────────────────────────
def handle_webhook_event(db, event: dict) -> str:
    """payment.captured / order.paid: finish orders whose app never came back."""
    kind = str(event.get('event') or '')
    if kind not in ('payment.captured', 'order.paid'):
        return 'ignored'
    entity = (((event.get('payload') or {}).get('payment') or {}).get('entity')) or {}
    payment_id = str(entity.get('id') or '')
    rp_order_id = str(entity.get('order_id') or '')
    if not payment_id or not rp_order_id:
        return 'ignored'
    order = Order.objects.filter(razorpay_order_id=rp_order_id, master=MASTER_POSTGRES).first()
    if order is None:
        return 'unknown-order'  # Cloud Function / website order: handled there
    if order.payment_verified:
        return 'already-paid'
    try:
        confirm_payment(db, order=order, payment_id=payment_id)
    except ApiError as exc:
        logger.warning('Webhook could not confirm %s: %s', order.id, exc.message)
        return 'rejected'
    return 'paid'


def order_json(order: Order) -> dict:
    """Firestore-shaped order for the app (OrderModel field names)."""
    document = decode(order.document)
    out = {}
    for key, value in document.items():
        out[key] = value.isoformat() if isinstance(value, datetime) else value
    out['id'] = order.id
    return out
