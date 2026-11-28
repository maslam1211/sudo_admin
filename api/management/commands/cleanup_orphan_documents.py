"""Remove private document files whose Firestore row is gone.

    python manage.py cleanup_orphan_documents          # dry run
    python manage.py cleanup_orphan_documents --apply

Rows disappear when the app deletes an account or a vehicle (it removes
`vehicleDocuments` rows directly). Run daily from cron so deleted users'
RC/DL photos don't stay on the server.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from api import firebase, private_storage
from api.models import PrivateFile


class Command(BaseCommand):
    help = 'Delete private vehicle-document files that no longer have a Firestore row.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        db = firebase.firestore_db()
        collection = db.collection('vehicleDocuments')
        removed = kept = 0
        for stored in PrivateFile.objects.filter(kind=PrivateFile.KIND_VEHICLE_DOCUMENT).iterator():
            if collection.document(stored.id).get().exists:
                kept += 1
                continue
            removed += 1
            self.stdout.write(f'  orphan {stored.id} ({stored.storage_path})')
            if apply:
                private_storage.delete(stored.storage_path)
                stored.delete()

        known = set(PrivateFile.objects.values_list('storage_path', flat=True))
        stray = 0
        docs_root = private_storage.root() / 'vehicle_documents'
        # Skip recent files: an upload in progress writes the file before its row.
        cutoff = time.time() - 3600
        if docs_root.exists():
            for path in docs_root.rglob('*'):
                if not path.is_file() or path.stat().st_mtime > cutoff:
                    continue
                if str(path.relative_to(private_storage.root())) not in known:
                    stray += 1
                    self.stdout.write(f'  stray file {path}')
                    if apply:
                        path.unlink(missing_ok=True)

        mode = 'APPLIED' if apply else 'DRY RUN (nothing deleted)'
        self.stdout.write(self.style.SUCCESS(f'{mode}: kept={kept}, orphan_rows={removed}, stray_files={stray}'))
