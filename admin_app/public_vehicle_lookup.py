"""
Public web lookup: plate / QR → notify screen URL.

Mirrors the mobile search rule: only vehicles with an activated, assigned QR.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from google.cloud.firestore_v1 import FieldFilter

MAX_VEHICLE_PHOTOS = 5  # unused here; keep import-free helpers only


def normalize_registration(raw: Any) -> str:
    if raw is None:
        return ''
    return ''.join(c for c in str(raw).upper().strip() if c.isalnum())


_QR_PATH_RE = re.compile(
    r'/admin/send-notification(?:-final)?/([A-Za-z0-9_-]+)/?',
    re.IGNORECASE,
)


def extract_qr_id_from_scan(raw: str) -> str | None:
    """Accept a full notify URL or a bare QR document id."""
    text = (raw or '').strip()
    if not text:
        return None
    m = _QR_PATH_RE.search(text)
    if m:
        return m.group(1)
    # Bare id (Firestore QR doc ids are typically alphanumeric)
    if re.fullmatch(r'[A-Za-z0-9_-]{6,64}', text):
        return text
    return None


def notify_url_for_qr(qr_id: str, request=None) -> str:
    qid = (qr_id or '').strip()
    path = f'/admin/send-notification/{qid}/'
    if request is not None:
        try:
            return request.build_absolute_uri(path)
        except Exception:
            pass
    base = (getattr(settings, 'BASE_DOMAIN', '') or 'https://sudotag.com').rstrip('/')
    return f'{base}{path}'


def lookup_vehicle_by_plate(db, plate_raw: str) -> dict[str, Any] | None:
    """
    Exact registration match (normalized). Returns first vehicle that has an
    activated QR (``isQrGenerated`` + ``qrCodeId``), same as the Flutter app search.
    """
    plate = normalize_registration(plate_raw)
    if len(plate) < 6:
        return None

    docs = list(
        db.collection('vehicles')
        .where(filter=FieldFilter('registrationNumber', '==', plate))
        .limit(10)
        .stream()
    )
    if not docs:
        docs = list(
            db.collection('vehicles')
            .where(filter=FieldFilter('vehicle_number', '==', plate))
            .limit(10)
            .stream()
        )

    for doc in docs:
        data = doc.to_dict() or {}
        if data.get('isQrGenerated') and str(data.get('qrCodeId') or '').strip():
            qr_id = str(data.get('qrCodeId')).strip()
            photos = data.get('photoUrls') if isinstance(data.get('photoUrls'), list) else []
            primary = ''
            for p in photos:
                s = str(p or '').strip()
                if s.startswith('http'):
                    primary = s
                    break
            return {
                'vehicle_id': doc.id,
                'qr_id': qr_id,
                'registrationNumber': data.get('registrationNumber') or plate,
                'make': data.get('make') or '',
                'model': data.get('model') or '',
                'primaryPhotoUrl': primary,
            }
    return None


def resolve_qr_for_notify(db, qr_id: str) -> dict[str, Any] | None:
    """Confirm QR exists and is usable for the public notify flow."""
    qid = (qr_id or '').strip()
    if not qid:
        return None
    snap = db.collection('qrcodes').document(qid).get()
    if not snap.exists:
        return {'qr_id': qid, 'exists': False}
    data = snap.to_dict() or {}
    return {
        'qr_id': qid,
        'exists': True,
        'isAssigned': bool(data.get('isAssigned')),
        'vehicleID': data.get('vehicleID') or data.get('vehicleId') or '',
    }
