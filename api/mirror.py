"""Copy all Firebase data (Firestore, Auth users, Storage files) into this server.

Read-only on the Firebase side. Run with `python manage.py mirror_firebase`
or let the worker run it on a schedule.

Firestore values are stored as JSON with tagged types so nothing is lost:

    Timestamp        -> {"__type": "timestamp", "value": "2026-11-28T10:00:00.123456+00:00"}
    GeoPoint         -> {"__type": "geopoint", "latitude": 9.9, "longitude": 76.2}
    DocumentReference-> {"__type": "ref", "path": "users/u1"}
    bytes            -> {"__type": "bytes", "base64": "..."}

`decode()` turns them back into Python values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from django.db import transaction
from django.utils import timezone as dj_timezone

from .models import FirebaseAuthUser, FirebaseStorageObject, FirestoreDocument, MirrorRun

logger = logging.getLogger(__name__)

BATCH = 300


# ─── value encoding ──────────────────────────────────────────────────────────
def encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return {'__type': 'timestamp', 'value': aware.isoformat()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'__type': 'bytes', 'base64': base64.b64encode(bytes(value)).decode('ascii')}
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if hasattr(value, 'latitude') and hasattr(value, 'longitude'):
        return {'__type': 'geopoint', 'latitude': value.latitude, 'longitude': value.longitude}
    if hasattr(value, 'path') and hasattr(value, 'id') and hasattr(value, 'parent'):
        return {'__type': 'ref', 'path': value.path}
    # Unknown type (e.g. vector): keep a readable form rather than failing.
    return {'__type': 'unknown', 'repr': repr(value)}


def decode(value: Any) -> Any:
    if isinstance(value, list):
        return [decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    kind = value.get('__type')
    if kind == 'timestamp':
        return datetime.fromisoformat(value['value'])
    if kind == 'bytes':
        return base64.b64decode(value['base64'])
    if kind in ('geopoint', 'ref', 'unknown'):
        return value
    return {k: decode(v) for k, v in value.items()}


def content_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    to_dt = getattr(value, 'ToDatetime', None)  # protobuf Timestamp
    if to_dt:
        return to_dt().replace(tzinfo=timezone.utc)
    return None


def _ms(value) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc) if value else None


# ─── Firestore ───────────────────────────────────────────────────────────────
def _iter_documents(collection, collection_path: str, stats: dict, only: set[str] | None):
    """Yield (path, collection_path, collection_id, doc_id, parent_path, snap_or_None, ref)."""
    collection_id = collection_path.rsplit('/', 1)[-1]
    parent_path = collection_path.rsplit('/', 1)[0] if '/' in collection_path else ''
    seen: set[str] = set()
    for snap in collection.stream():
        seen.add(snap.id)
        yield (f'{collection_path}/{snap.id}', collection_path, collection_id, snap.id,
               parent_path, snap, snap.reference)
    # Documents with no fields of their own but with subcollections.
    for ref in collection.list_documents(page_size=BATCH):
        if ref.id not in seen:
            stats['missing_parents'] += 1
            yield (f'{collection_path}/{ref.id}', collection_path, collection_id, ref.id,
                   parent_path, None, ref)


def _walk(collection, collection_path: str, stats: dict, only: set[str] | None):
    for item in _iter_documents(collection, collection_path, stats, only):
        yield item
        ref = item[6]
        for sub in ref.collections():
            yield from _walk(sub, f'{item[0]}/{sub.id}', stats, only)


def _flush(rows: list[FirestoreDocument], stats: dict) -> None:
    if not rows:
        return
    existing = dict(
        FirestoreDocument.objects.filter(path__in=[r.path for r in rows])
        .values_list('path', 'content_hash')
    )
    for row in rows:
        if row.path not in existing:
            stats['created'] += 1
        elif existing[row.path] != row.content_hash:
            stats['changed'] += 1
        else:
            stats['unchanged'] += 1
    FirestoreDocument.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=['path'],
        update_fields=['collection_path', 'collection_id', 'doc_id', 'parent_path', 'data',
                       'content_hash', 'create_time', 'update_time', 'synced_at', 'deleted_at'],
    )
    rows.clear()


def mirror_firestore(db, *, collections: Iterable[str] | None = None, now=None) -> dict:
    """Upsert every document; mark documents that vanished as deleted.

    Deletions are only marked when the whole walk finished without errors, so
    a network failure halfway can't flag live data as deleted.
    """
    now = now or dj_timezone.now()
    only = set(collections) if collections else None
    stats = {'documents': 0, 'created': 0, 'changed': 0, 'unchanged': 0,
             'missing_parents': 0, 'marked_deleted': 0, 'collections': 0, 'errors': 0}
    seen_paths: set[str] = set()
    rows: list[FirestoreDocument] = []
    roots = [c for c in db.collections() if only is None or c.id in only]
    for root in roots:
        stats['collections'] += 1
        try:
            for path, col_path, col_id, doc_id, parent, snap, _ref in _walk(root, root.id, stats, only):
                data = encode(snap.to_dict()) if snap is not None else None
                rows.append(FirestoreDocument(
                    path=path, collection_path=col_path, collection_id=col_id, doc_id=doc_id,
                    parent_path=parent, data=data,
                    content_hash=content_hash(data) if data is not None else '',
                    create_time=_dt(getattr(snap, 'create_time', None)) if snap is not None else None,
                    update_time=_dt(getattr(snap, 'update_time', None)) if snap is not None else None,
                    synced_at=now, deleted_at=None,
                ))
                seen_paths.add(path)
                stats['documents'] += 1
                if len(rows) >= BATCH:
                    _flush(rows, stats)
        except Exception:
            stats['errors'] += 1
            logger.exception('mirror: collection %s failed', root.id)
    _flush(rows, stats)

    if stats['errors'] == 0:
        scope = FirestoreDocument.objects.filter(deleted_at__isnull=True)
        if only is not None:
            from django.db.models import Q

            q = Q()
            for name in only:
                q |= Q(path__startswith=f'{name}/')
            scope = scope.filter(q)
        gone = [p for p in scope.values_list('path', flat=True).iterator() if p not in seen_paths]
        for i in range(0, len(gone), 1000):
            FirestoreDocument.objects.filter(path__in=gone[i:i + 1000]).update(deleted_at=now)
        stats['marked_deleted'] = len(gone)
    return stats


# ─── Firebase Auth ───────────────────────────────────────────────────────────
def mirror_auth(auth, *, now=None) -> dict:
    now = now or dj_timezone.now()
    stats = {'users': 0, 'marked_deleted': 0}
    seen: set[str] = set()
    page = auth.list_users()
    while page:
        for user in page.users:
            meta = getattr(user, 'user_metadata', None)
            FirebaseAuthUser.objects.update_or_create(uid=user.uid, defaults={
                'email': user.email or '',
                'phone_number': user.phone_number or '',
                'display_name': user.display_name or '',
                'photo_url': user.photo_url or '',
                'email_verified': bool(user.email_verified),
                'disabled': bool(user.disabled),
                'providers': [
                    {'providerId': p.provider_id, 'uid': p.uid, 'email': p.email or '',
                     'phoneNumber': p.phone_number or ''}
                    for p in (user.provider_data or [])
                ],
                'custom_claims': user.custom_claims or None,
                'created_at': _ms(getattr(meta, 'creation_timestamp', None)),
                'last_sign_in_at': _ms(getattr(meta, 'last_sign_in_timestamp', None)),
                'synced_at': now,
                'deleted_at': None,
            })
            seen.add(user.uid)
            stats['users'] += 1
        page = page.get_next_page()
    gone = FirebaseAuthUser.objects.filter(deleted_at__isnull=True).exclude(uid__in=seen)
    stats['marked_deleted'] = gone.update(deleted_at=now)
    return stats


# ─── Firebase Storage ────────────────────────────────────────────────────────
def mirror_storage(bucket, root: Path, *, now=None) -> dict:
    """Download new or changed files; keep files whose source was deleted."""
    now = now or dj_timezone.now()
    stats = {'files': 0, 'downloaded': 0, 'unchanged': 0, 'bytes': 0, 'marked_deleted': 0}
    base = (root / 'firebase_storage').resolve()
    seen: set[str] = set()
    for blob in bucket.list_blobs():
        if blob.name.endswith('/'):
            continue
        stats['files'] += 1
        seen.add(blob.name)
        target = (base / blob.name).resolve()
        if base not in target.parents:
            logger.warning('mirror: skipping unsafe storage path %r', blob.name)
            continue
        existing = FirebaseStorageObject.objects.filter(path=blob.name).first()
        if existing and existing.md5_hash == (blob.md5_hash or '') and target.exists():
            stats['unchanged'] += 1
            if existing.deleted_at:
                existing.deleted_at = None
                existing.save(update_fields=['deleted_at'])
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + '.part')
        blob.download_to_filename(str(tmp))
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        stats['downloaded'] += 1
        stats['bytes'] += int(blob.size or 0)
        FirebaseStorageObject.objects.update_or_create(path=blob.name, defaults={
            'bucket': getattr(bucket, 'name', ''),
            'size_bytes': int(blob.size or 0),
            'md5_hash': blob.md5_hash or '',
            'content_type': blob.content_type or '',
            'updated': _dt(blob.updated),
            'local_path': str(target.relative_to(root.resolve())),
            'synced_at': now,
            'deleted_at': None,
        })
    gone = FirebaseStorageObject.objects.filter(deleted_at__isnull=True).exclude(path__in=seen)
    stats['marked_deleted'] = gone.update(deleted_at=now)
    return stats


# ─── one full run ────────────────────────────────────────────────────────────
def run_full_mirror(*, db, auth=None, bucket=None, storage_root: Path | None = None,
                    collections: Iterable[str] | None = None) -> MirrorRun:
    run = MirrorRun.objects.create()
    stats: dict = {}
    status = 'ok'
    errors: list[str] = []
    for name, step in (
        ('firestore', lambda: mirror_firestore(db, collections=collections)),
        ('auth', (lambda: mirror_auth(auth)) if auth is not None else None),
        ('storage', (lambda: mirror_storage(bucket, storage_root)) if bucket is not None else None),
    ):
        if step is None:
            continue
        try:
            stats[name] = step()
            if stats[name].get('errors'):
                status = 'partial'
        except Exception as exc:
            logger.exception('mirror step %s failed', name)
            status = 'partial'
            errors.append(f'{name}: {type(exc).__name__}: {exc}')
    with transaction.atomic():
        run.finished_at = dj_timezone.now()
        run.status = status if stats else 'failed'
        run.stats = stats
        run.error = '\n'.join(errors)[:4000]
        run.save()
    return run
