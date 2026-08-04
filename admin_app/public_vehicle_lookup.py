"""
Public web lookup: plate / QR → notify screen URL.

Mirrors the mobile search rule: only vehicles with an activated, assigned QR.
Unassigned QRs are routed to the activate-id screen.
"""
from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from google.cloud.firestore_v1 import FieldFilter

MAX_VEHICLE_PHOTOS = 5  # unused here; keep import-free helpers only


def normalize_registration(raw: Any) -> str:
    if raw is None:
        return ''
    return ''.join(c for c in str(raw).upper().strip() if c.isalnum())


_QR_PATH_RE = re.compile(
    r'/admin/(?:send-notification(?:-final)?|activate-id)/([A-Za-z0-9_-]+)/?',
    re.IGNORECASE,
)


def extract_qr_id_from_scan(raw: str) -> str | None:
    """Accept a full notify/activate URL or a bare QR document id."""
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


def _absolute_admin_url(path: str, request=None) -> str:
    path = '/' + (path or '').lstrip('/')
    if request is not None:
        try:
            return request.build_absolute_uri(path)
        except Exception:
            pass
    base = (getattr(settings, 'BASE_DOMAIN', '') or 'https://sudotag.com').rstrip('/')
    return f'{base}{path}'


def notify_url_for_qr(qr_id: str, request=None) -> str:
    """Entry URL printed on stickers → check_id_enabled → notify or activate."""
    qid = (qr_id or '').strip()
    return _absolute_admin_url(f'/admin/send-notification/{qid}/', request)


def activate_url_for_qr(qr_id: str, request=None) -> str:
    """Direct activate-id screen for unassigned QRs."""
    qid = (qr_id or '').strip()
    return _absolute_admin_url(f'/admin/activate-id/{qid}/', request)


def notify_final_url_for_qr(qr_id: str, request=None) -> str:
    """Activated notify UI (send-notification-final)."""
    qid = (qr_id or '').strip()
    return _absolute_admin_url(f'/admin/send-notification-final/{qid}/', request)


def plate_ocr_variants(plate_raw: str) -> list[str]:
    """
    Normalized plate plus common OCR confusion swaps (O/0, I/1, …).
    Used when auto-read plates miss an exact Firestore match.
    """
    base = normalize_registration(plate_raw)
    if len(base) < 6:
        return []

    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        v = normalize_registration(value)
        if len(v) < 6 or v in seen:
            return
        seen.add(v)
        ordered.append(v)

    add(base)
    swaps = (
        ('O', '0'),
        ('0', 'O'),
        ('I', '1'),
        ('1', 'I'),
        ('S', '5'),
        ('5', 'S'),
        ('B', '8'),
        ('8', 'B'),
        ('Z', '2'),
        ('2', 'Z'),
        ('G', '6'),
        ('6', 'G'),
    )
    for a, b in swaps:
        if a in base:
            add(base.replace(a, b))

    # Position-aware: district digits after state code (KL10…)
    if len(base) >= 8 and base[:2].isalpha():
        chars = list(base)
        for idx in (2, 3):
            if chars[idx] == 'O':
                chars[idx] = '0'
            elif chars[idx] == 'I':
                chars[idx] = '1'
        add(''.join(chars))

    return ordered[:12]


def _vehicle_hit_from_docs(docs, fallback_plate: str) -> dict[str, Any] | None:
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
                'registrationNumber': data.get('registrationNumber') or fallback_plate,
                'make': data.get('make') or '',
                'model': data.get('model') or '',
                'primaryPhotoUrl': primary,
            }
    return None


def lookup_vehicle_by_plate(db, plate_raw: str) -> dict[str, Any] | None:
    """
    Exact registration match (normalized), then OCR confusion variants.
    Returns first vehicle that has an activated QR (``isQrGenerated`` + ``qrCodeId``).
    """
    variants = plate_ocr_variants(plate_raw)
    if not variants:
        return None

    for plate in variants:
        docs = list(
            db.collection('vehicles')
            .where(filter=FieldFilter('registrationNumber', '==', plate))
            .limit(10)
            .stream()
        )
        hit = _vehicle_hit_from_docs(docs, plate)
        if hit:
            return hit

        docs = list(
            db.collection('vehicles')
            .where(filter=FieldFilter('vehicle_number', '==', plate))
            .limit(10)
            .stream()
        )
        hit = _vehicle_hit_from_docs(docs, plate)
        if hit:
            return hit

    return None


def resolve_qr_for_notify(db, qr_id: str) -> dict[str, Any] | None:
    """Confirm QR exists and whether it is activated (assigned)."""
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
