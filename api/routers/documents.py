"""Vehicle documents (RC, driving licence, insurance, PUC) kept privately.

    POST   /api/v1/vehicles/{vehicle_id}/documents   multipart: file, documentType, documentName?, expiryDate?
    GET    /api/v1/documents/{document_id}/file
    DELETE /api/v1/documents/{document_id}

Before this, the app uploaded these photos to Cloudinary with an unsigned
preset and saved the public URL, so anyone with the link could open them.
Now the bytes stay on this server (api.private_storage) and are only
returned to the vehicle owner or the uploader — the same people the
`vehicleDocuments` Firestore rule allows.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from ninja import File, Form, Router, Schema
from ninja.files import UploadedFile

from .. import firebase, private_storage, ratelimit
from ..errors import ApiError
from ..models import PrivateFile
from ..security import firebase_auth

logger = logging.getLogger(__name__)

router = Router(tags=['documents'], auth=firebase_auth)

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
UPLOADS_PER_UID_HOUR = 40
DOCUMENT_TYPES = {'rcBook', 'insurance', 'pollution', 'drivingLicense', 'other'}


class DocumentOut(Schema):
    id: str
    vehicleId: str
    documentType: str
    documentName: str | None = None
    documentUrl: str
    expiryDate: str | None = None
    uploadedAt: str
    uploadedBy: str
    userId: str
    vehicleNumber: str | None = None


def document_file_url(document_id: str) -> str:
    base = str(getattr(settings, 'API_PUBLIC_BASE_URL', 'https://sudotag.com')).rstrip('/')
    return f'{base}/api/v1/documents/{document_id}/file'


def _parse_expiry(raw: str | None) -> datetime | None:
    value = (raw or '').strip()
    if not value:
        return None
    try:
        if 'T' in value:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return datetime.combine(date.fromisoformat(value), time(12, 0), tzinfo=timezone.utc)
    except ValueError:
        raise ApiError('invalid-argument', 'Expiry date is not valid.')


def _owns_vehicle(db, vehicle_id: str, uid: str) -> tuple[bool, dict]:
    if not vehicle_id:
        return False, {}
    snap = db.collection('vehicles').document(vehicle_id).get()
    if not snap.exists:
        return False, {}
    data = snap.to_dict() or {}
    return str(data.get('ownerId') or '') == uid, data


def _load_document_for(db, document_id: str, uid: str) -> tuple[object, dict]:
    """Document ref + data when `uid` may access it (vehicle owner or uploader)."""
    ref = db.collection('vehicleDocuments').document(document_id)
    snap = ref.get()
    if not snap.exists:
        raise ApiError('not-found', 'Document not found.')
    data = snap.to_dict() or {}
    owns, _ = _owns_vehicle(db, str(data.get('vehicleId') or ''), uid)
    if not (owns or str(data.get('userId') or '') == uid):
        # Same answer as "missing", so ids can't be probed.
        raise ApiError('not-found', 'Document not found.')
    return ref, data


@router.post('/vehicles/{vehicle_id}/documents', response={201: DocumentOut})
def upload_document(
    request,
    vehicle_id: str,
    file: UploadedFile = File(...),
    documentType: str = Form(...),
    documentName: str | None = Form(None),
    expiryDate: str | None = Form(None),
):
    uid = request.auth.uid
    if documentType not in DOCUMENT_TYPES:
        raise ApiError('invalid-argument', 'Unknown document type.')
    if file.size is not None and file.size > MAX_DOCUMENT_BYTES:
        raise ApiError('invalid-argument', 'This file is too large. The limit is 10 MB.')

    db = firebase.firestore_db()
    owns, vehicle = _owns_vehicle(db, vehicle_id, uid)
    if not owns:
        raise ApiError('permission-denied', 'You can only add documents to your own vehicles.')

    ratelimit.hit(f'doc-upload:{uid}', limit=UPLOADS_PER_UID_HOUR, window_seconds=3600)

    data = file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ApiError('invalid-argument', 'This file is too large. The limit is 10 MB.')
    if not data:
        raise ApiError('invalid-argument', 'The file is empty.')
    content_type = private_storage.sniff_content_type(data[:16])
    if content_type not in private_storage.ALLOWED_DOCUMENT_TYPES:
        raise ApiError('invalid-argument', 'Upload a photo (JPEG, PNG, WebP, HEIC) or a PDF.')

    expiry = _parse_expiry(expiryDate)
    doc_ref = db.collection('vehicleDocuments').document()
    relative, digest = private_storage.save_bytes(
        data=data, content_type=content_type, owner_uid=uid, vehicle_id=vehicle_id,
    )
    uploaded_at = datetime.now(timezone.utc)
    name = (documentName or '').strip()[:120] or None
    vehicle_number = str(vehicle.get('registrationNumber') or '').strip() or None
    firestore_row = {
        'vehicleId': vehicle_id,
        'documentType': documentType,
        'documentName': name,
        'documentUrl': document_file_url(doc_ref.id),
        'expiryDate': expiry,
        'uploadedAt': uploaded_at,
        'uploadedBy': uid,
        'userId': uid,
        'vehicleNumber': vehicle_number,
        'storage': 'private',
        'contentType': content_type,
    }
    try:
        with transaction.atomic():
            PrivateFile.objects.create(
                id=doc_ref.id, owner_uid=uid, vehicle_id=vehicle_id, storage_path=relative,
                content_type=content_type, size_bytes=len(data), sha256=digest,
            )
            doc_ref.set(firestore_row)
    except Exception:
        private_storage.delete(relative)
        PrivateFile.objects.filter(id=doc_ref.id).delete()
        logger.exception('Document upload failed vehicle=%s', vehicle_id)
        raise ApiError('internal', "Couldn't save the document. Please try again.")

    logger.info('Document stored privately id=%s vehicle=%s bytes=%d', doc_ref.id, vehicle_id, len(data))
    return 201, {
        'id': doc_ref.id,
        **{k: v for k, v in firestore_row.items() if k in DocumentOut.model_fields},
        'expiryDate': expiry.isoformat() if expiry else None,
        'uploadedAt': uploaded_at.isoformat(),
    }


@router.get('/documents/{document_id}/file')
def download_document(request, document_id: str):
    db = firebase.firestore_db()
    _, data = _load_document_for(db, document_id, request.auth.uid)
    stored = PrivateFile.objects.filter(id=document_id).first()
    if stored is None:
        # Still on Cloudinary (not copied yet): the app opens `documentUrl` itself.
        raise ApiError('not-found', 'Document file not found.')
    try:
        handle = open(private_storage.absolute(stored.storage_path), 'rb')
    except (OSError, ValueError):
        logger.error('Private file missing on disk id=%s', document_id)
        raise ApiError('not-found', 'Document file not found.')
    response = FileResponse(handle, content_type=stored.content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Disposition'] = 'inline'
    return response


@router.delete('/documents/{document_id}', response={204: None})
def delete_document(request, document_id: str):
    db = firebase.firestore_db()
    ref, _ = _load_document_for(db, document_id, request.auth.uid)
    stored = PrivateFile.objects.filter(id=document_id).first()
    ref.delete()
    if stored is not None:
        private_storage.delete(stored.storage_path)
        stored.delete()
    return 204, None
