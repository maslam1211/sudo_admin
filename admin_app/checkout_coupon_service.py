"""Web checkout — coupon codes and store pricing (Firestore)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from firebase_admin import firestore

logger = logging.getLogger(__name__)

COUPONS_COLLECTION = 'web_coupons'
SETTINGS_COLLECTION = 'web_checkout_settings'
SETTINGS_DOC_ID = 'default'

DEFAULT_STICKER_PRICE = 349.0
DEFAULT_SHIPPING_CHARGE = 49.0

DISCOUNT_TYPES = ('unit_price', 'fixed', 'percent')
CODE_RE = re.compile(r'^[A-Z0-9_-]{3,32}$')


def normalize_coupon_code(raw: str) -> str:
    return re.sub(r'\s+', '', str(raw or '').strip().upper())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_expiry(value: Any) -> datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if hasattr(value, 'to_datetime'):
        try:
            dt = value.to_datetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def get_checkout_settings(db) -> dict[str, float]:
    """Return sticker unit price + shipping from Firestore (with code defaults)."""
    try:
        snap = db.collection(SETTINGS_COLLECTION).document(SETTINGS_DOC_ID).get()
        if snap.exists:
            data = snap.to_dict() or {}
            price = float(data.get('stickerUnitPrice', DEFAULT_STICKER_PRICE))
            shipping = float(data.get('shippingCharge', DEFAULT_SHIPPING_CHARGE))
            return {
                'stickerUnitPrice': max(0.0, price),
                'shippingCharge': max(0.0, shipping),
            }
    except Exception as exc:
        logger.warning('get_checkout_settings failed: %s', exc)
    return {
        'stickerUnitPrice': DEFAULT_STICKER_PRICE,
        'shippingCharge': DEFAULT_SHIPPING_CHARGE,
    }


def save_checkout_settings(db, *, sticker_unit_price: float, shipping_charge: float) -> dict:
    payload = {
        'stickerUnitPrice': max(0.0, float(sticker_unit_price)),
        'shippingCharge': max(0.0, float(shipping_charge)),
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }
    db.collection(SETTINGS_COLLECTION).document(SETTINGS_DOC_ID).set(payload, merge=True)
    return {
        'stickerUnitPrice': payload['stickerUnitPrice'],
        'shippingCharge': payload['shippingCharge'],
    }


def list_coupons(db) -> list[dict]:
    rows: list[dict] = []
    try:
        for doc in db.collection(COUPONS_COLLECTION).stream():
            row = doc.to_dict() or {}
            row['id'] = doc.id
            row['code'] = row.get('code') or doc.id
            rows.append(row)
    except Exception as exc:
        logger.exception('list_coupons failed: %s', exc)
    rows.sort(key=lambda r: str(r.get('code') or ''))
    return rows


def get_coupon(db, code: str) -> Optional[dict]:
    norm = normalize_coupon_code(code)
    if not norm:
        return None
    try:
        snap = db.collection(COUPONS_COLLECTION).document(norm).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data['id'] = snap.id
        data['code'] = data.get('code') or snap.id
        return data
    except Exception as exc:
        logger.warning('get_coupon failed code=%s err=%s', norm, exc)
        return None


def _coupon_is_valid(coupon: dict, quantity: int) -> tuple[bool, str]:
    if not coupon.get('active', True):
        return False, 'This coupon code is not active.'

    expires = _parse_expiry(coupon.get('expiresAt'))
    if expires and _now_utc() >= expires:
        return False, 'This coupon code has expired.'

    min_qty = int(coupon.get('minQuantity') or 1)
    if quantity < min_qty:
        return False, f'This coupon requires at least {min_qty} item(s).'

    max_uses = coupon.get('maxUses')
    if max_uses not in (None, ''):
        try:
            cap = int(max_uses)
        except (TypeError, ValueError):
            cap = 0
        used = int(coupon.get('usedCount') or 0)
        if cap > 0 and used >= cap:
            return False, 'This coupon code has reached its usage limit.'

    return True, ''


def compute_coupon_discount(
    *,
    unit_price: float,
    quantity: int,
    coupon: dict,
) -> dict:
    """Return pricing breakdown after applying a coupon to product subtotal."""
    quantity = max(1, int(quantity))
    unit_price = max(0.0, float(unit_price))
    subtotal_before = round(unit_price * quantity, 2)

    dtype = str(coupon.get('discountType') or 'fixed').strip().lower()
    try:
        value = float(coupon.get('discountValue') or 0)
    except (TypeError, ValueError):
        value = 0.0

    if dtype == 'unit_price':
        effective_unit = max(0.0, value)
        subtotal_after = round(effective_unit * quantity, 2)
    elif dtype == 'percent':
        pct = max(0.0, min(100.0, value))
        subtotal_after = round(subtotal_before * (1.0 - pct / 100.0), 2)
    elif dtype == 'fixed':
        subtotal_after = round(max(0.0, subtotal_before - max(0.0, value)), 2)
    else:
        raise ValueError(f'Unsupported discount type: {dtype}')

    discount = round(max(0.0, subtotal_before - subtotal_after), 2)
    effective_unit = round(subtotal_after / quantity, 2) if quantity else subtotal_after

    return {
        'subtotalBefore': subtotal_before,
        'subtotalAfter': subtotal_after,
        'discount': discount,
        'effectiveUnitPrice': effective_unit,
        'discountType': dtype,
        'discountValue': value,
    }


def validate_coupon_for_checkout(
    db,
    *,
    code: str,
    quantity: int,
    unit_price: float | None = None,
) -> dict:
    """Validate coupon and return pricing preview for checkout."""
    norm = normalize_coupon_code(code)
    if not norm or not CODE_RE.match(norm):
        return {'ok': False, 'message': 'Enter a valid coupon code.'}

    coupon = get_coupon(db, norm)
    if not coupon:
        return {'ok': False, 'message': 'Invalid coupon code.'}

    ok, msg = _coupon_is_valid(coupon, quantity)
    if not ok:
        return {'ok': False, 'message': msg}

    if unit_price is None:
        unit_price = get_checkout_settings(db)['stickerUnitPrice']

    try:
        pricing = compute_coupon_discount(
            unit_price=float(unit_price),
            quantity=quantity,
            coupon=coupon,
        )
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}

    return {
        'ok': True,
        'message': coupon.get('label') or 'Coupon applied.',
        'code': norm,
        'label': coupon.get('label') or '',
        'discountType': pricing['discountType'],
        'discountValue': pricing['discountValue'],
        'unitPrice': float(unit_price),
        'effectiveUnitPrice': pricing['effectiveUnitPrice'],
        'quantity': quantity,
        'subtotalBefore': pricing['subtotalBefore'],
        'subtotal': pricing['subtotalAfter'],
        'discount': pricing['discount'],
    }


def save_coupon(db, payload: dict) -> dict:
    code = normalize_coupon_code(payload.get('code'))
    if not code or not CODE_RE.match(code):
        raise ValueError('Coupon code must be 3–32 characters (letters, numbers, _ or -).')

    dtype = str(payload.get('discountType') or 'unit_price').strip().lower()
    if dtype not in DISCOUNT_TYPES:
        raise ValueError('Invalid discount type.')

    try:
        discount_value = float(payload.get('discountValue'))
    except (TypeError, ValueError):
        raise ValueError('Discount value must be a number.')

    if dtype == 'percent' and not (0 < discount_value <= 100):
        raise ValueError('Percent discount must be between 1 and 100.')
    if dtype in ('fixed', 'unit_price') and discount_value < 0:
        raise ValueError('Discount value cannot be negative.')

    min_qty = int(payload.get('minQuantity') or 1)
    if min_qty < 1:
        min_qty = 1

    max_uses_raw = payload.get('maxUses')
    max_uses = None
    if max_uses_raw not in (None, ''):
        max_uses = int(max_uses_raw)
        if max_uses < 1:
            raise ValueError('Max uses must be at least 1.')

    expires_at = None
    expires_raw = (payload.get('expiresAt') or '').strip()
    if expires_raw:
        expires_at = _parse_expiry(expires_raw)
        if not expires_at:
            raise ValueError('Invalid expiry date.')

    doc = {
        'code': code,
        'label': str(payload.get('label') or '').strip(),
        'discountType': dtype,
        'discountValue': discount_value,
        'active': bool(payload.get('active', True)),
        'minQuantity': min_qty,
        'maxUses': max_uses,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }
    if expires_at:
        doc['expiresAt'] = expires_at

    ref = db.collection(COUPONS_COLLECTION).document(code)
    existing = ref.get()
    if existing.exists:
        ref.set(doc, merge=True)
    else:
        doc['usedCount'] = 0
        doc['createdAt'] = firestore.SERVER_TIMESTAMP
        ref.set(doc)

    saved = ref.get().to_dict() or {}
    saved['id'] = code
    saved['code'] = code
    return saved


def delete_coupon(db, code: str) -> bool:
    norm = normalize_coupon_code(code)
    if not norm:
        return False
    ref = db.collection(COUPONS_COLLECTION).document(norm)
    if not ref.get().exists:
        return False
    ref.delete()
    return True


def increment_coupon_use(db, code: str) -> None:
    norm = normalize_coupon_code(code)
    if not norm:
        return
    ref = db.collection(COUPONS_COLLECTION).document(norm)
    try:
        ref.update({
            'usedCount': firestore.Increment(1),
            'lastUsedAt': firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:
        logger.warning('increment_coupon_use failed code=%s err=%s', norm, exc)
