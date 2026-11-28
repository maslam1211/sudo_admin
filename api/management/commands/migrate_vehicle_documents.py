"""Copy every vehicle document from Cloudinary into private server storage.

    python manage.py migrate_vehicle_documents                 # dry run: report only
    python manage.py migrate_vehicle_documents --apply         # copy + repoint Firestore
    python manage.py migrate_vehicle_documents --apply --delete-public
                                                              # also remove the public Cloudinary copy

For each `vehicleDocuments` row still pointing at a public URL:
  1. download the file and check it is a real image/PDF,
  2. store it under PRIVATE_MEDIA_ROOT and record a PrivateFile row,
  3. set documentUrl to the API URL, keep the old URL in legacyDocumentUrl.

Nothing is deleted unless --delete-public is given, and then only after the
private copy is saved and its checksum verified. Safe to re-run: rows that
already have a private copy are skipped. Note that after step 3, app builds
older than the private-documents release can no longer open the document
(they don't send a sign-in token); the public copy keeps working for them
until --delete-public runs.
"""

from __future__ import annotations

import hashlib

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from api import firebase, private_storage
from api.models import PrivateFile
from api.routers.documents import MAX_DOCUMENT_BYTES, document_file_url


class Command(BaseCommand):
    help = 'Move vehicle documents from public Cloudinary URLs to private server storage.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write changes (default is a dry run).')
        parser.add_argument('--delete-public', action='store_true',
                            help='After a verified copy, delete the public Cloudinary file.')
        parser.add_argument('--limit', type=int, default=0, help='Stop after this many documents.')

    def handle(self, *args, apply=False, delete_public=False, limit=0, **opts):
        if delete_public and not apply:
            self.stderr.write('--delete-public needs --apply.')
            return
        db = firebase.firestore_db()
        stats = {'seen': 0, 'already_private': 0, 'copied': 0, 'would_copy': 0,
                 'deleted_public': 0, 'no_url': 0, 'failed': 0}

        for snap in db.collection('vehicleDocuments').stream():
            if limit and (stats['copied'] + stats['would_copy']) >= limit:
                break
            stats['seen'] += 1
            data = snap.to_dict() or {}
            existing = PrivateFile.objects.filter(id=snap.id).first()
            if existing is not None or data.get('storage') == 'private':
                stats['already_private'] += 1
                if apply and delete_public and existing is not None and existing.legacy_url:
                    if self._delete_public(existing.legacy_url, snap.id):
                        stats['deleted_public'] += 1
                        existing.legacy_url = ''
                        existing.save(update_fields=['legacy_url'])
                continue

            url = str(data.get('documentUrl') or '').strip()
            if not url.startswith('http'):
                stats['no_url'] += 1
                self.stdout.write(f'  skip {snap.id}: no URL')
                continue
            if not apply:
                stats['would_copy'] += 1
                self.stdout.write(f'  would copy {snap.id} ({data.get("documentType")}, vehicle {data.get("vehicleId")})')
                continue

            try:
                self._copy(db, snap, data, url)
                stats['copied'] += 1
                if delete_public and self._delete_public(url, snap.id):
                    stats['deleted_public'] += 1
                    PrivateFile.objects.filter(id=snap.id).update(legacy_url='')
            except Exception as exc:  # keep going; report at the end
                stats['failed'] += 1
                self.stderr.write(f'  FAILED {snap.id}: {exc}')

        mode = 'APPLIED' if apply else 'DRY RUN (nothing written)'
        self.stdout.write(self.style.SUCCESS(f'{mode}: ' + ', '.join(f'{k}={v}' for k, v in stats.items())))

    def _copy(self, db, snap, data, url):
        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_DOCUMENT_BYTES:
                raise ValueError('larger than 10 MB')
            chunks.append(chunk)
        body = b''.join(chunks)
        content_type = private_storage.sniff_content_type(body[:16])
        if content_type not in private_storage.ALLOWED_DOCUMENT_TYPES:
            raise ValueError('not an image or PDF')

        owner_uid = str(data.get('userId') or data.get('uploadedBy') or 'unknown')
        vehicle_id = str(data.get('vehicleId') or '')
        relative, digest = private_storage.save_bytes(
            data=body, content_type=content_type, owner_uid=owner_uid, vehicle_id=vehicle_id,
        )
        with open(private_storage.absolute(relative), 'rb') as fh:
            if hashlib.sha256(fh.read()).hexdigest() != digest:
                private_storage.delete(relative)
                raise ValueError('checksum mismatch after write')
        try:
            with transaction.atomic():
                PrivateFile.objects.create(
                    id=snap.id, owner_uid=owner_uid, vehicle_id=vehicle_id, storage_path=relative,
                    content_type=content_type, size_bytes=len(body), sha256=digest, legacy_url=url,
                )
                snap.reference.update({
                    'documentUrl': document_file_url(snap.id),
                    'legacyDocumentUrl': url,
                    'storage': 'private',
                    'contentType': content_type,
                })
        except Exception:
            private_storage.delete(relative)
            raise
        self.stdout.write(f'  copied {snap.id} ({len(body)} bytes)')

    def _delete_public(self, url: str, doc_id: str) -> bool:
        if 'res.cloudinary.com' not in url:
            return False
        from admin_app.vehicle_photos import delete_storage_url

        delete_storage_url(url)  # logs and swallows its own errors
        self.stdout.write(f'  removed public copy for {doc_id}')
        return True
