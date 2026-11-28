"""Copy all Firebase data into this server's database (read-only on Firebase).

    python manage.py mirror_firebase                    # Firestore + Auth users + Storage files
    python manage.py mirror_firebase --only users,vehicles
    python manage.py mirror_firebase --skip-storage --skip-auth

Results land in mirror_firestore_document, mirror_firebase_auth_user and
mirror_firebase_storage_object (files under PRIVATE_MEDIA_ROOT/firebase_storage/).
Safe to re-run; the worker runs it daily (MIRROR_INTERVAL_HOURS).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api import firebase, mirror


def default_sources(*, auth: bool = True, storage: bool = True) -> dict:
    sources = {'db': firebase.firestore_db()}
    if auth:
        sources['auth'] = firebase.auth_module()
    if storage:
        from firebase_admin import storage as fb_storage

        from admin_app.firebase_init import ensure_firebase_app

        sources['bucket'] = fb_storage.bucket(app=ensure_firebase_app())
        sources['storage_root'] = Path(settings.PRIVATE_MEDIA_ROOT)
    return sources


class Command(BaseCommand):
    help = 'Mirror Firestore, Firebase Auth users and Firebase Storage into this server.'

    def add_arguments(self, parser):
        parser.add_argument('--only', default='', help='Comma-separated root collections (default: all).')
        parser.add_argument('--skip-auth', action='store_true')
        parser.add_argument('--skip-storage', action='store_true')

    def handle(self, *args, only='', skip_auth=False, skip_storage=False, **opts):
        collections = [c.strip() for c in only.split(',') if c.strip()] or None
        sources = default_sources(auth=not skip_auth, storage=not skip_storage)
        run = mirror.run_full_mirror(collections=collections, **sources)
        for name, stats in run.stats.items():
            self.stdout.write(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
        if run.error:
            self.stderr.write(run.error)
        if run.status == 'failed':
            raise CommandError('Mirror failed.')
        style = self.style.SUCCESS if run.status == 'ok' else self.style.WARNING
        self.stdout.write(style(f'Mirror run #{run.pk}: {run.status}'))
