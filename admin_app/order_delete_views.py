"""Delete orders from the admin panel.

Each order is copied to `deleted_orders/{id}` (with who deleted it and when)
before it is removed from `orders`, so a mistaken delete can be recovered.
The order's QR code, vehicle and payment records are not touched.
"""

from __future__ import annotations

import json
import logging

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from firebase_admin import firestore

logger = logging.getLogger(__name__)

ORDERS = 'orders'
DELETED = 'deleted_orders'
MAX_PER_REQUEST = 100


def _get_db():
    from .views import db
    return db


def _ids(request):
    try:
        body = json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        body = {}
    raw = body.get('orderIds') or request.POST.getlist('orderIds')
    if isinstance(raw, str):
        raw = [raw]
    seen, out = set(), []
    for value in raw or []:
        value = str(value).strip()
        if value and '/' not in value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def delete_orders(db, order_ids, admin_email):
    """Archive then delete. Returns (deleted_ids, missing_ids)."""
    deleted, missing = [], []
    batch = db.batch()
    pending = 0
    for order_id in order_ids:
        ref = db.collection(ORDERS).document(order_id)
        snap = ref.get()
        if not snap.exists:
            missing.append(order_id)
            continue
        archived = dict(snap.to_dict() or {})
        archived.update({
            'originalId': order_id,
            'deletedAt': firestore.SERVER_TIMESTAMP,
            'deletedBy': admin_email or 'admin',
        })
        batch.set(db.collection(DELETED).document(order_id), archived)
        batch.delete(ref)
        deleted.append(order_id)
        pending += 2
        if pending >= 400:  # Firestore allows 500 writes per batch
            batch.commit()
            batch, pending = db.batch(), 0
    if pending:
        batch.commit()
    return deleted, missing


@require_POST
def orders_delete(request):
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required.'}, status=403)
    order_ids = _ids(request)
    if not order_ids:
        return JsonResponse({'success': False, 'error': 'Choose at least one order.'}, status=400)
    if len(order_ids) > MAX_PER_REQUEST:
        return JsonResponse({'success': False, 'error': f'Delete at most {MAX_PER_REQUEST} orders at a time.'}, status=400)
    try:
        deleted, missing = delete_orders(_get_db(), order_ids, request.session.get('email') or '')
    except Exception:
        logger.exception('orders_delete failed for %s', order_ids)
        return JsonResponse({'success': False, 'error': 'Could not delete the orders. Try again.'}, status=500)
    logger.info('admin %s deleted orders %s', request.session.get('email'), deleted)
    for key in ('dashboard_stats', 'analytics_raw_v2'):
        cache.delete(key)
    return JsonResponse({'success': True, 'deleted': deleted, 'missing': missing})
