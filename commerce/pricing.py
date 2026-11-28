"""Checkout pricing — exact port of functions/checkout_coupons.js.

This is what app customers are charged, so it must give the same totals as
the Cloud Function to the paisa. Rounding mirrors JavaScript `Math.round`
(halves round up), not Python's round-half-even. Pure functions only; the
caller passes the settings document and the coupon.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_UNIT_PRICE = 199
TAG_MODELS = {'current': 799, 'lite': 199, 'smart': 349, 'pro': 699, 'premium': 999, 'sticker': 799}
DEFAULT_SHIPPING = 49
CODE_RE = re.compile(r'^[A-Z0-9_-]{3,32}$')
TAG_PRICE_FIELDS = {
    'current': 'currentCustomerPrice',
    'sticker': 'currentCustomerPrice',
    'lite': 'webLitePrice',
    'smart': 'smartPrice',
    'pro': 'proPrice',
    'premium': 'premiumPrice',
}
UNIT_PRICE_KEYS = ('sudoTagPrice', 'sudotagPrice', 'sudo_tag_price', 'stickerUnitPrice',
                   'productPrice', 'unitPrice', 'price')
SHIPPING_KEYS = ('shippingCharge', 'shipping', 'shippingPrice')


def _number(value: Any) -> float:
    """JS Number(value) for the inputs Firestore can hold."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip()) if value.strip() else 0.0
        except ValueError:
            return math.nan
    if value is None:
        return 0.0
    return math.nan


def round2(value: Any) -> float:
    n = _number(value)
    if not math.isfinite(n):
        return 0.0
    # Math.round(x) == floor(x + 0.5)
    return math.floor(n * 100 + 0.5) / 100


def _first_positive(data: dict, keys, fallback):
    for key in keys:
        if data.get(key) is None or data.get(key) == '':
            continue
        n = round2(data[key])
        if n > 0:
            return n
    return fallback


def _first_non_negative(data: dict, keys, fallback):
    for key in keys:
        if data.get(key) is None or data.get(key) == '':
            continue
        n = round2(data[key])
        if math.isfinite(n) and n >= 0:
            return n
    return fallback


def normalize_coupon_code(raw: Any) -> str:
    if raw is None:
        return ''
    return re.sub(r'\s+', '', str(raw)).upper()


def normalize_quantity(raw: Any) -> int:
    """JS parseInt + clamp(1, 20)."""
    match = re.match(r'^\s*([+-]?\d+)', str(raw)) if raw is not None else None
    if not match:
        return 1
    return min(20, max(1, int(match.group(1))))


def parse_expires_at(value: Any) -> Optional[datetime]:
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(value, dict) and isinstance(value.get('_seconds'), (int, float)):
        return datetime.fromtimestamp(value['_seconds'], tz=timezone.utc)
    return None


def unit_and_shipping(settings: dict) -> tuple[float, float]:
    data = settings or {}
    return (
        _first_positive(data, UNIT_PRICE_KEYS, DEFAULT_UNIT_PRICE),
        _first_non_negative(data, SHIPPING_KEYS, DEFAULT_SHIPPING),
    )


def tag_price(settings: dict, product_key: Any, fallback_unit: float) -> Optional[float]:
    key = str(product_key or '').strip()
    field = TAG_PRICE_FIELDS.get(key)
    if not field:
        return None
    data = settings or {}
    direct = round2(data.get(field))
    if direct > 0:
        return direct
    if key == 'lite':
        legacy = round2(data.get('litePrice'))
        if legacy > 0:
            return legacy
    if key in ('current', 'sticker'):
        return TAG_MODELS['current']
    return TAG_MODELS.get(key) or fallback_unit


def compute_coupon_discount(*, unit_price, quantity, shipping, coupon: Optional[dict]) -> dict:
    qty = normalize_quantity(quantity)
    list_unit = round2(unit_price)
    ship = round2(shipping)
    subtotal_before = round2(list_unit * qty)
    subtotal_after = subtotal_before
    if coupon:
        kind = str(coupon.get('discountType') or '').strip()
        value = _number(coupon.get('discountValue'))
        safe = value if math.isfinite(value) else 0.0
        if kind == 'unit_price':
            subtotal_after = round2(max(0.0, safe) * qty)
        elif kind == 'percent':
            pct = min(100.0, max(0.0, safe))
            subtotal_after = round2(subtotal_before * (1 - pct / 100))
        elif kind == 'fixed':
            subtotal_after = round2(max(0.0, subtotal_before - max(0.0, safe)))
    return {
        'unitPrice': list_unit,
        'effectiveUnitPrice': round2(subtotal_after / qty),
        'quantity': qty,
        'subtotalBefore': subtotal_before,
        'subtotal': subtotal_after,
        'discount': round2(max(0.0, subtotal_before - subtotal_after)),
        'shipping': ship,
        'total': round2(subtotal_after + ship),
    }


def coupon_validity_error(coupon: Optional[dict], quantity: int, now: Optional[datetime] = None) -> Optional[str]:
    if not coupon or coupon.get('active') is not True:
        return 'This coupon code is not active.'
    now = now or datetime.now(timezone.utc)
    expires = parse_expires_at(coupon.get('expiresAt'))
    if expires and now >= expires:
        return 'This coupon code has expired.'
    min_qty = 1 if coupon.get('minQuantity') is None else _number(coupon.get('minQuantity'))
    min_qty = min_qty if math.isfinite(min_qty) else 1
    if quantity < min_qty:
        shown = int(min_qty) if float(min_qty).is_integer() else min_qty
        return f"This coupon requires at least {shown} {'item' if min_qty == 1 else 'items'}."
    max_uses = None if coupon.get('maxUses') is None else _number(coupon.get('maxUses'))
    used = 0.0 if coupon.get('usedCount') is None else _number(coupon.get('usedCount'))
    if max_uses is not None and max_uses > 0 and math.isfinite(max_uses) and math.isfinite(used) and used >= max_uses:
        return 'This coupon code has reached its usage limit.'
    return None


def _quote(unit_price, shipping, coupon, quantity) -> dict:
    pricing = compute_coupon_discount(unit_price=unit_price, quantity=quantity, shipping=shipping, coupon=coupon)
    if not coupon:
        return {**pricing, 'code': None, 'label': None, 'message': None,
                'discountType': None, 'discountValue': None}
    label = str(coupon.get('label') or '')
    return {
        **pricing,
        'code': coupon.get('code') or None,
        'label': label or None,
        'message': label or 'Coupon applied.',
        'discountType': coupon.get('discountType') or None,
        'discountValue': _number(coupon['discountValue']) if coupon.get('discountValue') is not None else None,
    }


def validate_coupon_for_checkout(*, settings: dict, coupon_lookup, coupon_code, quantity, product_key,
                                 now: Optional[datetime] = None) -> dict:
    """Same contract as the JS: {'ok': True, 'quote': …} or {'ok': False, 'error': …}.

    `coupon_lookup(code)` returns the stored coupon dict or None.
    """
    unit, shipping = unit_and_shipping(settings)
    model_price = tag_price(settings, product_key, unit)
    if model_price:
        unit = model_price
    qty = normalize_quantity(quantity)
    code = normalize_coupon_code(coupon_code)
    if not code:
        return {'ok': True, 'quote': _quote(unit, shipping, None, qty)}
    if not CODE_RE.match(code):
        return {'ok': False, 'error': 'Enter a valid coupon code.'}
    stored = coupon_lookup(code)
    if stored is None:
        return {'ok': False, 'error': 'Invalid coupon code.'}
    coupon = {**stored, 'code': normalize_coupon_code(stored.get('code')) if stored.get('code') else code}
    error = coupon_validity_error(coupon, qty, now)
    if error:
        return {'ok': False, 'error': error}
    return {'ok': True, 'quote': _quote(unit, shipping, coupon, qty)}


def order_coupon_fields(quote: dict) -> dict:
    fields = {
        'unitPrice': quote['unitPrice'],
        'subtotal': quote['subtotal'],
        'subtotalBeforeDiscount': quote['subtotalBefore'],
        'couponDiscount': quote['discount'],
        'shippingCharge': quote['shipping'],
        'amount': quote['total'],
    }
    if quote.get('code'):
        fields['couponCode'] = quote['code']
        fields['coupon'] = {
            'code': quote['code'],
            'label': quote.get('label') or '',
            'discountType': quote.get('discountType'),
            'discountValue': quote.get('discountValue'),
            'discount': quote['discount'],
            'subtotalBefore': quote['subtotalBefore'],
        }
    return fields


def active_coupon_offer(coupon: dict, now: Optional[datetime] = None) -> Optional[dict]:
    """Entry for the "available offers" list, or None when not usable now."""
    if coupon.get('active') is not True:
        return None
    now = now or datetime.now(timezone.utc)
    expires = parse_expires_at(coupon.get('expiresAt'))
    if expires and now >= expires:
        return None
    max_uses = None if coupon.get('maxUses') is None else _number(coupon.get('maxUses'))
    used = 0.0 if coupon.get('usedCount') is None else _number(coupon.get('usedCount'))
    if max_uses is not None and max_uses > 0 and math.isfinite(max_uses) and math.isfinite(used) and used >= max_uses:
        return None
    return {
        'code': coupon.get('code'),
        'label': coupon.get('label') or '',
        'description': coupon.get('description') or '',
        'discountType': coupon.get('discountType') or None,
        'discountValue': _number(coupon['discountValue']) if coupon.get('discountValue') is not None else None,
        'minQuantity': _number(coupon['minQuantity']) if coupon.get('minQuantity') is not None else 1,
        'expiresAt': expires.isoformat().replace('+00:00', 'Z') if expires else None,
    }
