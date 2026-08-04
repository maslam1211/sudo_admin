"""Firestore helpers for the SudoTag Feedback Management System (collection: feedbacks)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

import pytz
from firebase_admin import firestore

logger = logging.getLogger(__name__)

COLLECTION = 'feedbacks'
LEGACY_COLLECTION = 'feedback'
IST = pytz.timezone('Asia/Kolkata')

STATUS_PENDING = 'pending'
STATUS_APPROVED = 'approved'
STATUS_REJECTED = 'rejected'


def _db():
    from admin_app.views import db
    return db


def _as_int_rating(value: Any, default: int = 0) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(5, rating)) if rating else default


def _format_created_at(value: Any) -> str:
    if value is None:
        return ''
    try:
        if hasattr(value, 'strftime'):
            dt = value
            if getattr(dt, 'tzinfo', None):
                dt = dt.astimezone(IST)
            else:
                dt = IST.localize(dt)
            return dt.strftime('%d %b %Y')
        if isinstance(value, datetime):
            return value.strftime('%d %b %Y')
        if isinstance(value, str):
            return value
    except Exception:
        pass
    return ''


def _sort_key(item: dict) -> float:
    raw = item.get('_created_raw')
    if raw is None:
        return 0.0
    try:
        if hasattr(raw, 'timestamp'):
            return float(raw.timestamp())
        if isinstance(raw, datetime):
            return raw.timestamp()
    except Exception:
        pass
    return 0.0


def normalize_feedback_doc(doc_id: str, data: Optional[dict]) -> dict:
    data = data or {}
    rating = _as_int_rating(data.get('rating'), 0)
    status = (data.get('status') or '').strip().lower()
    is_approved = bool(data.get('isApproved'))

    # Legacy docs from collection `feedback` have no status flags.
    if not status:
        if is_approved:
            status = STATUS_APPROVED
        elif data.get('feedback') or data.get('name'):
            status = STATUS_PENDING
        else:
            status = STATUS_PENDING

    if status == STATUS_APPROVED:
        is_approved = True
    elif status == STATUS_REJECTED:
        is_approved = False

    created_raw = data.get('createdAt') or data.get('timestamp')
    return {
        'id': doc_id,
        'name': (data.get('name') or 'Anonymous').strip() or 'Anonymous',
        'email': (data.get('email') or '').strip(),
        'rating': rating,
        'feedback': (data.get('feedback') or '').strip(),
        'status': status,
        'isApproved': is_approved,
        'profileImage': (data.get('profileImage') or '').strip(),
        'createdAt': _format_created_at(created_raw),
        '_created_raw': created_raw,
    }


def create_feedback(
    *,
    name: str,
    feedback: str,
    rating: int,
    email: str = '',
    status: str = STATUS_PENDING,
    is_approved: bool = False,
    profile_image: str = '',
    created_at=None,
) -> str:
    feedback_id = str(uuid.uuid4())
    payload = {
        'name': name.strip(),
        'email': (email or '').strip(),
        'rating': _as_int_rating(rating),
        'feedback': feedback.strip(),
        'createdAt': created_at if created_at is not None else firestore.SERVER_TIMESTAMP,
        'status': status,
        'isApproved': bool(is_approved),
        'profileImage': (profile_image or '').strip(),
    }
    _db().collection(COLLECTION).document(feedback_id).set(payload)
    return feedback_id


def update_feedback(feedback_id: str, fields: dict) -> None:
    allowed = {
        'name', 'email', 'rating', 'feedback', 'status',
        'isApproved', 'profileImage', 'createdAt',
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    if 'rating' in payload:
        payload['rating'] = _as_int_rating(payload['rating'])
    if 'status' in payload:
        status = str(payload['status']).strip().lower()
        payload['status'] = status
        if status == STATUS_APPROVED:
            payload['isApproved'] = True
        elif status == STATUS_REJECTED:
            payload['isApproved'] = False
    if not payload:
        return
    _db().collection(COLLECTION).document(feedback_id).update(payload)


def delete_feedback_doc(feedback_id: str) -> None:
    # Prefer new collection; also try legacy if needed.
    ref = _db().collection(COLLECTION).document(feedback_id)
    if ref.get().exists:
        ref.delete()
        return
    legacy = _db().collection(LEGACY_COLLECTION).document(feedback_id)
    if legacy.get().exists:
        legacy.delete()


def get_feedback(feedback_id: str) -> Optional[dict]:
    snap = _db().collection(COLLECTION).document(feedback_id).get()
    if snap.exists:
        return normalize_feedback_doc(snap.id, snap.to_dict())
    snap = _db().collection(LEGACY_COLLECTION).document(feedback_id).get()
    if snap.exists:
        return normalize_feedback_doc(snap.id, snap.to_dict())
    return None


def list_all_feedbacks() -> list[dict]:
    items: list[dict] = []
    seen = set()
    for collection in (COLLECTION, LEGACY_COLLECTION):
        try:
            for doc in _db().collection(collection).stream():
                if doc.id in seen:
                    continue
                seen.add(doc.id)
                items.append(normalize_feedback_doc(doc.id, doc.to_dict()))
        except Exception as exc:
            logger.error('Failed reading %s: %s', collection, exc)
    items.sort(key=_sort_key, reverse=True)
    return items


def list_approved_feedbacks(limit: int = 50) -> list[dict]:
    items: list[dict] = []
    try:
        query = (
            _db()
            .collection(COLLECTION)
            .where('isApproved', '==', True)
            .limit(limit)
        )
        for doc in query.stream():
            item = normalize_feedback_doc(doc.id, doc.to_dict())
            if item['status'] == STATUS_APPROVED and item['feedback']:
                items.append(item)
    except Exception as exc:
        logger.error('Approved feedback query failed, falling back: %s', exc)
        for item in list_all_feedbacks():
            if item.get('isApproved') and item.get('status') == STATUS_APPROVED and item.get('feedback'):
                items.append(item)

    items.sort(key=_sort_key, reverse=True)
    return items[:limit]


def compute_stats(items: Optional[list[dict]] = None) -> dict:
    items = items if items is not None else list_all_feedbacks()
    total = len(items)
    pending = sum(1 for i in items if i.get('status') == STATUS_PENDING)
    approved = sum(1 for i in items if i.get('status') == STATUS_APPROVED or i.get('isApproved'))
    rejected = sum(1 for i in items if i.get('status') == STATUS_REJECTED)
    ratings = [i.get('rating', 0) for i in items if i.get('rating')]
    average = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    return {
        'total': total,
        'pending': pending,
        'approved': approved,
        'rejected': rejected,
        'average_rating': average,
    }


def upload_profile_image(file_obj) -> str:
    """Upload optional profile image via Cloudinary; return URL or empty string."""
    if not file_obj:
        return ''
    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            file_obj,
            folder='sudotag/feedback',
            resource_type='image',
        )
        return result.get('secure_url') or ''
    except Exception as exc:
        logger.error('Feedback image upload failed: %s', exc)
        raise
