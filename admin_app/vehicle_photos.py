"""
Admin helpers for vehicle gallery photos.

Uploads use Cloudinary (same pipeline as the Flutter app / ads / vehicle docs).
Download URLs are stored on ``vehicles/{id}.photoUrls`` only — no other fields
are modified. Max 5 photos.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import unquote

import cloudinary.uploader

logger = logging.getLogger(__name__)

MAX_VEHICLE_PHOTOS = 5
# Legacy Firebase Storage bucket (older admin uploads); delete still supported.
STORAGE_BUCKET = 'sudotag-57673.firebasestorage.app'


def parse_photo_urls(vehicle_data: dict | None) -> list[str]:
    data = vehicle_data if isinstance(vehicle_data, dict) else {}
    raw = data.get('photoUrls') or data.get('photo_urls')
    if isinstance(raw, str) and raw.strip():
        raw = [raw]
    if not isinstance(raw, list):
        return []
    urls: list[str] = []
    for item in raw:
        url = str(item or '').strip()
        if url.startswith('http://') or url.startswith('https://'):
            urls.append(url)
        if len(urls) >= MAX_VEHICLE_PHOTOS:
            break
    return urls


def primary_photo_url(vehicle_data: dict | None) -> str | None:
    urls = parse_photo_urls(vehicle_data)
    return urls[0] if urls else None


def upload_vehicle_photo_bytes(
    *,
    owner_id: str,
    vehicle_id: str,
    content: bytes,
    content_type: str = 'image/jpeg',
) -> str:
    """
    Upload image bytes to Cloudinary folder ``vehicle_photos/{vehicle_id}``.
    Returns the secure HTTPS URL for Firestore ``photoUrls``.
    """
    vid = (vehicle_id or 'unknown').strip() or 'unknown'
    owner = (owner_id or 'unknown').strip() or 'unknown'
    public_id = f'{uuid.uuid4().hex}'
    result = cloudinary.uploader.upload(
        content,
        folder=f'vehicle_photos/{vid}',
        public_id=public_id,
        resource_type='image',
        overwrite=False,
        tags=['vehicle_photo', owner],
    )
    url = (result or {}).get('secure_url') or (result or {}).get('url')
    if not url:
        raise RuntimeError('Cloudinary upload returned no URL')
    return str(url)


def delete_storage_url(download_url: str) -> None:
    """
    Best-effort delete. Cloudinary public_id is derived from the URL path when
    possible; legacy Firebase Storage URLs are deleted from the bucket.
    Failures are logged and never raised to the caller.
    """
    url = (download_url or '').strip()
    if not url:
        return
    try:
        if 'res.cloudinary.com' in url:
            # .../image/upload/v123/vehicle_photos/vid/file.jpg
            marker = '/upload/'
            if marker in url:
                path = url.split(marker, 1)[1]
                # Drop version segment vNNNN/
                parts = path.split('/')
                if parts and parts[0].startswith('v') and parts[0][1:].isdigit():
                    parts = parts[1:]
                public_id = '/'.join(parts)
                if public_id.rsplit('.', 1)[-1].lower() in (
                    'jpg',
                    'jpeg',
                    'png',
                    'webp',
                    'gif',
                ):
                    public_id = public_id.rsplit('.', 1)[0]
                if public_id:
                    cloudinary.uploader.destroy(public_id, resource_type='image')
            return

        from firebase_admin import storage

        bucket = storage.bucket(STORAGE_BUCKET)
        if 'firebasestorage.googleapis.com' in url and '/o/' in url:
            path = unquote(url.split('/o/', 1)[1].split('?', 1)[0])
            bucket.blob(path).delete()
            return
        marker = f'/{STORAGE_BUCKET}/'
        if marker in url:
            path = unquote(url.split(marker, 1)[1].split('?', 1)[0])
            bucket.blob(path).delete()
    except Exception as exc:
        logger.warning('Vehicle photo storage delete skipped: %s', exc)


def set_vehicle_photo_urls(db, vehicle_id: str, photo_urls: list[str]) -> list[str]:
    cleaned = [str(u).strip() for u in photo_urls if str(u).strip()][:MAX_VEHICLE_PHOTOS]
    db.collection('vehicles').document(vehicle_id).update({'photoUrls': cleaned})
    return cleaned


def enrich_vehicle_for_admin(vehicle_dict: dict[str, Any]) -> dict[str, Any]:
    v = dict(vehicle_dict or {})
    urls = parse_photo_urls(v)
    v['photoUrls'] = urls
    v['primaryPhotoUrl'] = urls[0] if urls else None
    v['hasPhotos'] = bool(urls)
    return v
