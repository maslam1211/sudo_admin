"""Checkout and orders.

    GET  /api/v1/checkout/settings                 public   (prices, shipping, buying open)
    POST /api/v1/checkout/quote                    signed in  {couponCode?, quantity, productKey?}
    GET  /api/v1/checkout/coupons                  signed in
    POST /api/v1/orders                            signed in  -> {order, razorpayOrderId, amountPaise, quote}
    GET  /api/v1/orders                            signed in  (mine, newest first)
    POST /api/v1/orders/{id}/payment               signed in  {razorpayPaymentId, razorpaySignature?}
    POST /api/v1/orders/{id}/payment-failed        signed in
    POST /api/v1/orders/{id}/cancel                signed in
    POST /api/v1/webhooks/razorpay                 Razorpay (X-Razorpay-Signature)

Replaces the Cloud Functions createOrder, validateCheckoutCoupon,
listCheckoutCoupons and verifyPayment, and the app's direct order writes.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from ninja import Router, Schema

from commerce import razorpay_guard, service

from .. import firebase, ratelimit
from ..errors import ApiError
from ..security import firebase_auth

logger = logging.getLogger(__name__)

public_router = Router(tags=['checkout'])
router = Router(tags=['checkout'], auth=firebase_auth)

ORDERS_PER_UID_HOUR = 20


class QuoteIn(Schema):
    couponCode: str | None = None
    quantity: int = 1
    productKey: str | None = None


class PaymentIn(Schema):
    razorpayPaymentId: str
    razorpaySignature: str | None = None




@public_router.get('/checkout/settings')
def checkout_settings(request):
    data = service.settings_document(firebase.firestore_db())
    out = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in data.items()}
    out['orderingOpen'] = service.ordering_open(data)
    out['orderingClosedMessage'] = service.ordering_closed_message(data)
    return out


@router.post('/checkout/quote')
def checkout_quote(request, body: QuoteIn):
    if body.couponCode and len(body.couponCode.strip()) < 3:
        raise ApiError('invalid-argument', 'Enter a valid coupon code.')
    return {'quote': service.quote(firebase.firestore_db(), coupon_code=body.couponCode,
                                   quantity=body.quantity, product_key=body.productKey)}


@router.get('/checkout/coupons')
def checkout_coupons(request):
    return {'coupons': service.available_offers()}


@router.post('/orders', response={201: dict})
def create_order(request):
    try:
        payload = json.loads(request.body or b'{}')
    except (TypeError, ValueError):
        raise ApiError('invalid-argument', 'Invalid request.')
    if not isinstance(payload, dict):
        raise ApiError('invalid-argument', 'Invalid request.')
    uid = request.auth.uid
    ratelimit.hit(f'order-create:{uid}', limit=ORDERS_PER_UID_HOUR, window_seconds=3600,
                  message='Too many orders started. Please try again later.')
    order, quote = service.create_order(firebase.firestore_db(), uid=uid, payload=payload)
    return 201, {
        'order': service.order_json(order),
        'razorpayOrderId': order.razorpay_order_id,
        'amountPaise': service.paise(quote['total']),
        'currency': 'INR',
        'quote': quote,
    }


@router.get('/orders')
def list_orders(request):
    return {'orders': [service.order_json(o) for o in service.user_orders(request.auth.uid)]}


@router.post('/orders/{order_id}/payment')
def confirm_payment(request, order_id: str, body: PaymentIn):
    order = service.confirm_user_payment(
        firebase.firestore_db(), uid=request.auth.uid, order_id=order_id,
        payment_id=body.razorpayPaymentId.strip(), signature=(body.razorpaySignature or '').strip(),
    )
    return {'verified': True, 'order': service.order_json(order)}


@router.post('/orders/{order_id}/payment-failed')
def payment_failed(request, order_id: str):
    order = service.mark_payment_failed(firebase.firestore_db(), uid=request.auth.uid, order_id=order_id)
    return {'order': service.order_json(order)}


@router.post('/orders/{order_id}/cancel')
def cancel_order(request, order_id: str):
    order = service.cancel_order(firebase.firestore_db(), uid=request.auth.uid, order_id=order_id)
    return {'order': service.order_json(order)}


@public_router.post('/webhooks/razorpay')
def razorpay_webhook(request):
    secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '') or ''
    signature = request.headers.get('X-Razorpay-Signature', '')
    if not razorpay_guard.webhook_signature_matches(request.body, signature, secret):
        logger.warning('Razorpay webhook with a bad or missing signature')
        return JsonResponse({'ok': False}, status=401)
    try:
        event = json.loads(request.body or b'{}')
    except (TypeError, ValueError):
        return JsonResponse({'ok': False}, status=400)
    outcome = service.handle_webhook_event(firebase.firestore_db(), event)
    return {'ok': True, 'outcome': outcome}
