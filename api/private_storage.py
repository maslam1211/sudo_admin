"""Private files on the server's disk.

Files go under PRIVATE_MEDIA_ROOT (default: <project>/private_media, set
`SUDOTAG_PRIVATE_MEDIA_ROOT` on the VPS). That folder is **not** served by
nginx or WhiteNoise; bytes only leave through API views that check ownership.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from django.conf import settings

ALLOWED_DOCUMENT_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/heic': '.heic',
    'application/pdf': '.pdf',
}

# Magic numbers, so a renamed file can't claim to be an image.
_SIGNATURES = (
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'%PDF-', 'application/pdf'),
)


def root() -> Path:
    path = Path(getattr(settings, 'PRIVATE_MEDIA_ROOT'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def sniff_content_type(head: bytes) -> str:
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if len(head) >= 12 and head[4:8] == b'ftyp' and head[8:12] in (b'heic', b'heix', b'mif1', b'msf1', b'hevc'):
        return 'image/heic'
    return ''


def _safe_segment(value: str) -> str:
    cleaned = ''.join(c for c in str(value) if c.isalnum() or c in '-_')
    return cleaned[:128] or 'x'


def save_bytes(*, data: bytes, content_type: str, owner_uid: str, vehicle_id: str) -> tuple[str, str]:
    """Write bytes; returns (relative storage path, sha256 hex)."""
    ext = ALLOWED_DOCUMENT_TYPES[content_type]
    relative = os.path.join(
        'vehicle_documents', _safe_segment(owner_uid), _safe_segment(vehicle_id),
        f'{uuid.uuid4().hex}{ext}',
    )
    target = root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.part')
    with open(tmp, 'wb') as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)
    os.chmod(target, 0o600)
    return relative, hashlib.sha256(data).hexdigest()


def absolute(relative: str) -> Path:
    base = root().resolve()
    path = (base / relative).resolve()
    if base not in path.parents:
        raise ValueError('path escapes private media root')
    return path


def delete(relative: str) -> None:
    try:
        absolute(relative).unlink(missing_ok=True)
    except ValueError:
        pass
