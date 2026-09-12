"""Admin panel — web checkout pricing & coupon codes."""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .checkout_coupon_service import (
    DEFAULT_SHIPPING_CHARGE,
    DEFAULT_STICKER_PRICE,
    DISCOUNT_TYPES,
    delete_coupon,
    get_checkout_settings,
    list_coupons,
    save_checkout_settings,
    save_coupon,
    validate_coupon_for_checkout,
)
from .checkout_views import _get_db, _json_body

logger = logging.getLogger(__name__)


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _format_coupon_for_template(row: dict) -> dict:
    expires = row.get('expiresAt')
    expires_display = ''
    if expires is not None:
        if hasattr(expires, 'strftime'):
            expires_display = expires.strftime('%Y-%m-%d %H:%M UTC')
        else:
            expires_display = str(expires)
    dtype = row.get('discountType') or 'unit_price'
    try:
        val = float(row.get('discountValue') or 0)
    except (TypeError, ValueError):
        val = 0.0
    if dtype == 'unit_price':
        discount_label = f'Set unit price to ₹{val:.0f}'
    elif dtype == 'percent':
        discount_label = f'{val:.0f}% off subtotal'
    else:
        discount_label = f'₹{val:.0f} off subtotal'
    return {
        **row,
        'expiresDisplay': expires_display,
        'discountLabel': discount_label,
        'active': bool(row.get('active', True)),
        'usedCount': int(row.get('usedCount') or 0),
        'maxUses': row.get('maxUses'),
        'minQuantity': int(row.get('minQuantity') or 1),
    }


@require_GET
def manage_checkout_coupons(request):
    gate = _require_admin(request)
    if gate:
        return gate

    db = _get_db()
    settings = get_checkout_settings(db)
    coupons = [_format_coupon_for_template(c) for c in list_coupons(db)]

    return render(
        request,
        'manage_checkout_coupons.html',
        {
            'settings': settings,
            'coupons': coupons,
            'discount_types': DISCOUNT_TYPES,
            'default_sticker_price': DEFAULT_STICKER_PRICE,
            'default_shipping': DEFAULT_SHIPPING_CHARGE,
        },
    )


@csrf_exempt
@require_POST
def checkout_settings_save(request):
    gate = _require_admin(request)
    if gate:
        return JsonResponse({'success': False, 'error': 'Admin access required'}, status=403)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'}, status=400)

    try:
        sticker = float(data.get('stickerUnitPrice'))
        shipping = float(data.get('shippingCharge'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Enter valid numbers for price and shipping.'}, status=400)

    if sticker < 0 or shipping < 0:
        return JsonResponse({'success': False, 'error': 'Price and shipping cannot be negative.'}, status=400)

    try:
        saved = save_checkout_settings(_get_db(), sticker_unit_price=sticker, shipping_charge=shipping)
    except Exception as exc:
        logger.exception('checkout_settings_save failed: %s', exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    return JsonResponse({'success': True, 'settings': saved})


@csrf_exempt
@require_POST
def checkout_coupon_save(request):
    gate = _require_admin(request)
    if gate:
        return JsonResponse({'success': False, 'error': 'Admin access required'}, status=403)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'}, status=400)

    try:
        saved = save_coupon(_get_db(), data)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        logger.exception('checkout_coupon_save failed: %s', exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    return JsonResponse({
        'success': True,
        'coupon': _format_coupon_for_template(saved),
    })


@csrf_exempt
@require_POST
def checkout_coupon_delete(request):
    gate = _require_admin(request)
    if gate:
        return JsonResponse({'success': False, 'error': 'Admin access required'}, status=403)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'}, status=400)

    code = (data.get('code') or '').strip()
    if not code:
        return JsonResponse({'success': False, 'error': 'Coupon code is required.'}, status=400)

    try:
        ok = delete_coupon(_get_db(), code)
    except Exception as exc:
        logger.exception('checkout_coupon_delete failed: %s', exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    if not ok:
        return JsonResponse({'success': False, 'error': 'Coupon not found.'}, status=404)

    return JsonResponse({'success': True})


@csrf_exempt
@require_POST
def checkout_validate_coupon(request):
    """Public API — preview coupon discount for the buy page."""
    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'}, status=400)

    code = (data.get('couponCode') or data.get('code') or '').strip()
    try:
        quantity = int(data.get('quantity') or 1)
    except (TypeError, ValueError):
        quantity = 1

    db = _get_db()
    settings = get_checkout_settings(db)
    unit_price = settings['stickerUnitPrice']
    shipping = settings['shippingCharge']

    result = validate_coupon_for_checkout(
        db,
        code=code,
        quantity=quantity,
        unit_price=unit_price,
    )

    if not result.get('ok'):
        return JsonResponse({
            'success': False,
            'error': result.get('message') or 'Invalid coupon code.',
        }, status=400)

    total = round(float(result['subtotal']) + shipping, 2)
    return JsonResponse({
        'success': True,
        'coupon': {
            'code': result['code'],
            'label': result.get('label') or '',
            'message': result.get('message') or 'Coupon applied.',
            'discountType': result['discountType'],
            'discountValue': result['discountValue'],
            'unitPrice': result['unitPrice'],
            'effectiveUnitPrice': result['effectiveUnitPrice'],
            'quantity': result['quantity'],
            'subtotalBefore': result['subtotalBefore'],
            'subtotal': result['subtotal'],
            'discount': result['discount'],
            'shipping': shipping,
            'total': total,
        },
    })
