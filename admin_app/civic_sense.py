"""Civic Sense (community posts) moderation for the admin panel.

The mobile app stores posts in Firestore `community_posts`. Customers report a
post, which raises its `reportsCount`; the individual reports are read from the
post's `reports` subcollection, or from a top-level `community_reports`
collection keyed by `postId`, whichever the app writes.

Moderation writes the same fields the app already uses for removed posts:
status, moderationStatus, isDeleted, moderatedBy, moderatedAt, moderationNote.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from django.core.cache import cache
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)

POSTS = 'community_posts'
TOP_LEVEL_REPORTS = 'community_reports'
OPEN_COUNT_CACHE_KEY = 'civic_sense_open_reports'
LIST_LIMIT = 500

# action -> fields written on the post
ACTIONS: Dict[str, Dict[str, Any]] = {
    'approve': {'status': 'active', 'moderationStatus': 'approved', 'isDeleted': False},
    'remove': {'status': 'removed', 'moderationStatus': 'rejected', 'isDeleted': True},
    'dismiss': {'status': 'active', 'moderationStatus': 'approved', 'isDeleted': False, 'reportsCount': 0},
}
REPORT_RESOLUTION = {'approve': 'kept', 'remove': 'removed', 'dismiss': 'dismissed'}

FILTERS = ('reported', 'pending', 'live', 'removed', 'all')


def _first(data: Dict[str, Any], *keys: str, default: Any = '') -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ''):
            return value
    return default


def _as_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if hasattr(value, 'to_datetime'):
        try:
            return value.to_datetime()
        except Exception:
            return None
    return None


def _int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def post_state(data: Dict[str, Any]) -> str:
    """One of: removed, reported, pending, live."""
    status = str(data.get('status') or '').lower()
    moderation = str(data.get('moderationStatus') or '').lower()
    if data.get('isDeleted') is True or status in ('removed', 'deleted') or moderation == 'rejected':
        return 'removed'
    if _int(_first(data, 'reportsCount', 'reportCount', default=0)) > 0:
        return 'reported'
    if moderation in ('', 'pending', 'review', 'in_review'):
        return 'pending'
    return 'live'


def normalize_post(doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    images = [u for u in (data.get('imageUrls') or []) if isinstance(u, str) and u.startswith('http')]
    single = data.get('imageUrl')
    if isinstance(single, str) and single.startswith('http') and single not in images:
        images.insert(0, single)
    return {
        'id': doc_id,
        'title': str(_first(data, 'title', default='')).strip(),
        'text': str(_first(data, 'description', 'text', default='')).strip(),
        'images': images,
        'category': str(_first(data, 'category', default='General')),
        'tags': [str(t) for t in (data.get('tags') or []) if t],
        'author_id': str(_first(data, 'authorId', 'userId', default='')),
        'author_name': str(_first(data, 'authorName', default='')) or 'Unknown',
        'author_photo': data.get('authorPhotoUrl') or '',
        'likes': _int(_first(data, 'likesCount', 'likeCount', default=0)),
        'comments': _int(_first(data, 'commentsCount', 'commentCount', default=0)),
        'reports': _int(_first(data, 'reportsCount', 'reportCount', default=0)),
        'state': post_state(data),
        'status': str(data.get('status') or ''),
        'moderation_status': str(data.get('moderationStatus') or ''),
        'moderation_note': str(data.get('moderationNote') or ''),
        'moderated_by': str(data.get('moderatedBy') or ''),
        'moderated_at': _as_datetime(data.get('moderatedAt')),
        'created_at': _as_datetime(data.get('createdAt')),
    }


def list_posts(db, state: str = 'reported', query: str = '') -> Dict[str, Any]:
    """Posts newest first, plus per-state counts for the filter chips."""
    posts: List[Dict[str, Any]] = []
    try:
        stream = (
            db.collection(POSTS)
            .order_by('createdAt', direction=firestore.Query.DESCENDING)
            .limit(LIST_LIMIT)
            .stream()
        )
        posts = [normalize_post(d.id, d.to_dict() or {}) for d in stream]
    except Exception as exc:
        logger.warning('civic sense: ordered read failed (%s), reading unordered', exc)
        posts = [normalize_post(d.id, d.to_dict() or {}) for d in db.collection(POSTS).limit(LIST_LIMIT).stream()]
        posts.sort(key=lambda p: p['created_at'] or datetime.min, reverse=True)

    counts = {key: 0 for key in FILTERS}
    for post in posts:
        counts[post['state']] = counts.get(post['state'], 0) + 1
    counts['all'] = len(posts)

    if state != 'all':
        posts = [p for p in posts if p['state'] == state]
    if state == 'reported':
        posts.sort(key=lambda p: p['reports'], reverse=True)

    needle = query.strip().lower()
    if needle:
        posts = [
            p for p in posts
            if needle in ' '.join([p['title'], p['text'], p['author_name'], p['category'], p['id'], ' '.join(p['tags'])]).lower()
        ]
    return {'posts': posts, 'counts': counts}


def normalize_report(doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': doc_id,
        'reporter_id': str(_first(data, 'reporterId', 'reportedBy', 'userId', 'uid', default='')),
        'reporter_name': str(_first(data, 'reporterName', 'reportedByName', 'userName', default='')),
        'reason': str(_first(data, 'reason', 'category', 'type', default='Not given')),
        'details': str(_first(data, 'details', 'description', 'message', 'text', 'comment', default='')),
        'status': str(_first(data, 'status', default='open')),
        'created_at': _as_datetime(_first(data, 'createdAt', 'reportedAt', 'timestamp', default=None)),
    }


def _report_refs(db, post_id: str) -> Iterable:
    post_ref = db.collection(POSTS).document(post_id)
    yield from post_ref.collection('reports').stream()
    try:
        yield from (
            db.collection(TOP_LEVEL_REPORTS)
            .where(filter=FieldFilter('postId', '==', post_id))
            .stream()
        )
    except Exception as exc:
        logger.warning('civic sense: community_reports read failed: %s', exc)


def get_reports(db, post_id: str) -> List[Dict[str, Any]]:
    reports = [normalize_report(d.id, d.to_dict() or {}) for d in _report_refs(db, post_id)]
    reports.sort(key=lambda r: r['created_at'] or datetime.min, reverse=True)
    return reports


def get_comments(db, post_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    comments = []
    try:
        for d in db.collection(POSTS).document(post_id).collection('comments').limit(limit).stream():
            data = d.to_dict() or {}
            comments.append({
                'id': d.id,
                'author_name': str(_first(data, 'authorName', 'userName', default='Unknown')),
                'author_id': str(_first(data, 'authorId', 'userId', default='')),
                'text': str(_first(data, 'text', 'comment', 'message', default='')),
                'created_at': _as_datetime(data.get('createdAt')),
            })
    except Exception as exc:
        logger.warning('civic sense: comments read failed: %s', exc)
    comments.sort(key=lambda c: c['created_at'] or datetime.min)
    return comments


def get_users(db, user_ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """Name, email and phone for the post author and reporters."""
    users: Dict[str, Dict[str, str]] = {}
    for uid in {u for u in user_ids if u}:
        try:
            snap = db.collection('users').document(uid).get()
        except Exception:
            continue
        if not snap.exists:
            continue
        data = snap.to_dict() or {}
        users[uid] = {
            'name': str(_first(data, 'fullName', 'name', 'displayName', 'userName', default='')),
            'email': str(_first(data, 'emailAddress', 'email', default='')),
            'phone': str(_first(data, 'contactNumber', 'phoneNumber', 'mobileNumber', 'phone', default='')),
        }
    return users


def moderate(db, post_id: str, action: str, admin_email: str, note: str = '') -> Dict[str, Any]:
    """Approve, remove or dismiss reports on a post. Returns the fields written."""
    if action not in ACTIONS:
        raise ValueError('Unknown action.')
    post_ref = db.collection(POSTS).document(post_id)
    if not post_ref.get().exists:
        raise ValueError('That post no longer exists.')

    updates = dict(ACTIONS[action])
    updates.update({
        'moderatedBy': admin_email or 'admin',
        'moderatedAt': firestore.SERVER_TIMESTAMP,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    })
    note = (note or '').strip()[:500]
    if note:
        updates['moderationNote'] = note
    post_ref.update(updates)

    resolution = REPORT_RESOLUTION[action]
    for report in _report_refs(db, post_id):
        try:
            report.reference.update({
                'status': resolution,
                'resolvedBy': admin_email or 'admin',
                'resolvedAt': firestore.SERVER_TIMESTAMP,
            })
        except Exception as exc:
            logger.warning('civic sense: could not mark report %s: %s', report.id, exc)

    cache.delete(OPEN_COUNT_CACHE_KEY)
    return updates


def open_report_count(db) -> int:
    """Posts with reports that are still live; cached for a minute for the sidebar badge."""
    cached = cache.get(OPEN_COUNT_CACHE_KEY)
    if cached is not None:
        return cached
    count = 0
    try:
        for d in db.collection(POSTS).where(filter=FieldFilter('reportsCount', '>', 0)).stream():
            if post_state(d.to_dict() or {}) == 'reported':
                count += 1
    except Exception as exc:
        logger.warning('civic sense: open report count failed: %s', exc)
    cache.set(OPEN_COUNT_CACHE_KEY, count, 60)
    return count
