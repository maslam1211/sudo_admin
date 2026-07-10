"""
Razorpay helpers mirroring the mobile app Cloud Functions
(`createOrder` / `verifyPayment` in sudo/functions/index.js).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RAZORPAY_ORDERS_URL = 'https://api.razorpay.com/v1/orders'
RAZORPAY_PAYMENTS_URL = 'https://api.razorpay.com/v1/payments'


def get_razorpay_credentials() -> tuple[str, str]:
    key_id = (getattr(settings, 'RAZORPAY_KEY_ID', None) or '').strip()
    key_secret = (getattr(settings, 'RAZORPAY_KEY_SECRET', None) or '').strip()
    if not key_id or not key_secret:
        raise RuntimeError('Razorpay credentials are not configured')
    return key_id, key_secret


def create_razorpay_order(*, amount_paise: int, user_id: str = 'anonymous') -> dict[str, Any]:
    """Create a Razorpay order. Amount must already be in paise (same as mobile)."""
    if amount_paise < 100:
        raise ValueError('Amount must be at least 100 paise (1 INR)')

    key_id, key_secret = get_razorpay_credentials()
    payload = {
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': f'receipt_{int(time.time() * 1000)}',
        'notes': {
            'userId': user_id or 'anonymous',
            'source': 'website',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
    }

    response = requests.post(
        RAZORPAY_ORDERS_URL,
        json=payload,
        auth=(key_id, key_secret),
        timeout=30,
    )
    if response.status_code >= 400:
        detail = response.json() if response.content else {}
        description = (
            detail.get('error', {}).get('description')
            if isinstance(detail, dict)
            else None
        ) or response.text
        logger.error('Razorpay create order failed: %s', description)
        raise RuntimeError(f'Razorpay API Error: {description}')

    order = response.json()
    return {
        'id': order['id'],
        'amount': order['amount'],
        'currency': order.get('currency', 'INR'),
        'receipt': order.get('receipt'),
    }


def fetch_razorpay_payment(payment_id: str) -> dict[str, Any]:
    key_id, key_secret = get_razorpay_credentials()
    response = requests.get(
        f'{RAZORPAY_PAYMENTS_URL}/{payment_id}',
        auth=(key_id, key_secret),
        timeout=30,
    )
    if response.status_code >= 400:
        detail = response.json() if response.content else {}
        description = (
            detail.get('error', {}).get('description')
            if isinstance(detail, dict)
            else None
        ) or response.text
        raise RuntimeError(f'Razorpay payment fetch failed: {description}')
    return response.json()


def _signature_matches(order_id: str, payment_id: str, provided_signature: str) -> bool:
    _, key_secret = get_razorpay_credentials()
    body = f'{order_id}|{payment_id}'
    expected = hmac.new(
        key_secret.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided_signature.strip())


def verify_razorpay_payment(
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str | None = None,
) -> dict[str, Any]:
    """
    Mirror Cloud Function verifyPayment:
    - Prefer Razorpay payment status (captured/authorized)
    - Verify HMAC signature when provided
    - Fall back to captured status if signature mismatches
    """
    is_verified = False
    actual_order_id = razorpay_order_id
    verification_method = 'api'

    try:
        payment = fetch_razorpay_payment(razorpay_payment_id)
        if payment.get('order_id'):
            actual_order_id = payment['order_id']

        status = payment.get('status')
        if status not in ('captured', 'authorized'):
            return {
                'verified': False,
                'reason': f"Payment status is {status}, expected 'captured' or 'authorized'",
                'actualOrderId': actual_order_id,
            }

        signature = (razorpay_signature or '').strip()
        if signature:
            verification_method = 'signature'
            order_ids_to_try = []
            if actual_order_id:
                order_ids_to_try.append(actual_order_id)
            if razorpay_order_id and razorpay_order_id != actual_order_id:
                order_ids_to_try.append(razorpay_order_id)

            if not order_ids_to_try:
                is_verified = True
            else:
                for order_id in order_ids_to_try:
                    if _signature_matches(order_id, razorpay_payment_id, signature):
                        is_verified = True
                        actual_order_id = order_id
                        break

            # Same fallback as mobile Cloud Function
            if not is_verified and status == 'captured':
                logger.warning(
                    'Signature verification failed but payment is CAPTURED; marking verified'
                )
                is_verified = True
                verification_method = 'api_fallback'
        else:
            is_verified = True
            verification_method = 'api'

    except Exception as api_error:
        logger.exception('Error fetching payment from Razorpay: %s', api_error)
        signature = (razorpay_signature or '').strip()
        if signature:
            is_verified = _signature_matches(
                razorpay_order_id, razorpay_payment_id, signature
            )
            verification_method = 'signature_fallback'
        else:
            is_verified = False

    return {
        'verified': is_verified,
        'actualOrderId': actual_order_id,
        'verificationMethod': verification_method,
    }
