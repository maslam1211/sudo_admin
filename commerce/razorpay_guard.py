"""Server-side Razorpay checks — port of functions/payment_guard.js.

Everything is checked against Razorpay's API with our secret, never against
values the app sends:
  - the payment is captured or authorized, in INR;
  - when Razorpay knows the payment's order, it is the order being paid;
  - the amount paid equals what the server charged;
  - the payment id is claimed once, for one purpose — checked in PostgreSQL
    *and* in Firestore payment_claims, so a payment already used through the
    old Cloud Function can't be used again here (and vice versa).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

import requests
from django.db import IntegrityError, transaction

from admin_app.razorpay_service import (
    RAZORPAY_ORDERS_URL, RAZORPAY_PAYMENTS_URL, get_razorpay_credentials,
)

from .models import MASTER_POSTGRES, PaymentClaim


class PaymentRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _get(url: str) -> dict:
    key_id, key_secret = get_razorpay_credentials()
    response = requests.get(url, auth=(key_id, key_secret), timeout=30)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    return response.json()


def fetch_payment(payment_id: str) -> dict:
    return _get(f'{RAZORPAY_PAYMENTS_URL}/{payment_id}')


def fetch_order(order_id: str) -> dict:
    return _get(f'{RAZORPAY_ORDERS_URL}/{order_id}')


def create_order(*, amount_paise: int, receipt: str, notes: dict) -> dict:
    if amount_paise < 100:
        raise ValueError('Amount must be at least 100 paise (1 INR)')
    key_id, key_secret = get_razorpay_credentials()
    response = requests.post(
        RAZORPAY_ORDERS_URL,
        json={'amount': amount_paise, 'currency': 'INR', 'receipt': receipt[:40],
              'notes': {k: str(v) for k, v in notes.items()}},
        auth=(key_id, key_secret), timeout=30,
    )
    response.raise_for_status()
    return response.json()


def check_payment(*, payment_id: str, order_id: str, expected_amount_paise: int | None = None,
                  fetch=None, fetch_rp_order=None) -> tuple[dict, dict | None]:
    """Returns (payment, razorpay_order_or_None). Raises PaymentRejected."""
    fetch = fetch or fetch_payment
    fetch_rp_order = fetch_rp_order or fetch_order
    if not payment_id or not order_id:
        raise PaymentRejected('Missing payment id or order id.')
    payment = fetch(payment_id)
    if not payment or payment.get('id') != payment_id:
        raise PaymentRejected('Payment not found.')
    if payment.get('status') not in ('captured', 'authorized'):
        raise PaymentRejected(f"Payment is {payment.get('status')}.")
    if payment.get('currency') and payment['currency'] != 'INR':
        raise PaymentRejected(f"Payment currency is {payment['currency']}.")
    if payment.get('order_id') and payment['order_id'] != order_id:
        raise PaymentRejected('Payment belongs to a different order.')
    rp_order = None
    expected = expected_amount_paise
    if expected is None:
        rp_order = fetch_rp_order(order_id)
        expected = rp_order.get('amount') if rp_order else None
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise PaymentRejected('Could not determine the amount due.')
    if expected <= 0:
        raise PaymentRejected('Could not determine the amount due.')
    if int(payment.get('amount') or -1) != expected:
        raise PaymentRejected('Payment amount does not match the amount due.')
    return payment, rp_order


def signature_matches(order_id: str, payment_id: str, signature: str) -> bool:
    _, key_secret = get_razorpay_credentials()
    expected = hmac.new(key_secret.encode(), f'{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or '').strip())


def webhook_signature_matches(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _claim_in_firestore(db, ref, purpose: str, uid: str) -> None:
    """Transactional, like payment_guard.claimPayment, so this and the Cloud
    Function can never both claim one payment."""
    from google.cloud import firestore as gcf

    @gcf.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        if snap.exists:
            if (snap.to_dict() or {}).get('purpose') != purpose:
                raise PaymentRejected('This payment has already been used.')
            return
        tx.set(ref, {'purpose': purpose, 'uid': uid or None, 'claimedAt': datetime.now(timezone.utc)})

    run(db.transaction())


def claim_payment(db, *, payment_id: str, purpose: str, uid: str = '') -> None:
    """Claim in Firestore (shared with the Cloud Function) then PostgreSQL.
    Claiming the same payment for the same purpose again is fine (retries)."""
    existing = PaymentClaim.objects.filter(payment_id=payment_id).first()
    if existing and existing.purpose != purpose:
        raise PaymentRejected('This payment has already been used.')
    _claim_in_firestore(db, db.collection('payment_claims').document(payment_id), purpose, uid)
    if existing is None:
        try:
            with transaction.atomic():
                PaymentClaim.objects.create(payment_id=payment_id, purpose=purpose, uid=uid or '',
                                            claimed_at=datetime.now(timezone.utc), master=MASTER_POSTGRES)
        except IntegrityError:
            if PaymentClaim.objects.get(payment_id=payment_id).purpose != purpose:
                raise PaymentRejected('This payment has already been used.')


def receipt_id() -> str:
    return f'receipt_{int(time.time() * 1000)}'
