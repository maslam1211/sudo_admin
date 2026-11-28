"""Phase 4a: fill PostgreSQL with user data and prove nothing is missing.

    python manage.py migrate_accounts            # reconcile only (read-only)
    python manage.py migrate_accounts --apply    # import, then reconcile

Compares every users document, every document in every subcollection under
users (found by listing, at any depth), blocked_users, family_members and
daily_usage — record by record, both directions. Exits non-zero on any
difference. Never writes to Firestore.

Presence fields (isOnline, lastSeen, …) change every few seconds, so a
"different" right after an import usually means the user was active; run it
again.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts import sync
from accounts.models import UserProfile, UserSettings, UserSubDocument
from api import firebase
from api.mirror import encode

from .migrate_phase2 import _compare


def _walk(ref, base: str, out: dict) -> None:
    for sub in ref.collections():
        streamed = set()
        for snap in sub.stream():
            streamed.add(snap.id)
            out[f'{base}/{sub.id}/{snap.id}'] = encode(snap.to_dict() or {})
            _walk(snap.reference, f'{base}/{sub.id}/{snap.id}', out)
        for child in sub.list_documents():
            if child.id not in streamed:
                _walk(child, f'{base}/{sub.id}/{child.id}', out)


class Command(BaseCommand):
    help = 'Import user data from Firestore and reconcile it with PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        db = firebase.firestore_db()
        if apply:
            self.stdout.write(f'import accounts: {sync.import_everything(db)}')

        live = {'deleted_at__isnull': True}
        problems: list[str] = []
        users = {s.id: encode(s.to_dict() or {}) for s in db.collection('users').stream()}
        sub_docs: dict = {}
        uids = set(users) | {r.id for r in db.collection('users').list_documents()}
        for uid in uids:
            _walk(db.collection('users').document(uid), f'users/{uid}', sub_docs)

        def settings_path(uid):
            return f'users/{uid}/{sync.SETTINGS_SUB}/{uid}'

        settings_fs = {uid: sub_docs[settings_path(uid)] for uid in uids if settings_path(uid) in sub_docs}
        other_fs = {p: d for p, d in sub_docs.items() if p != settings_path(p.split('/')[1])}

        report = {
            'users': _compare('users', users, {r.uid: r.document for r in UserProfile.objects.filter(**live)},
                              problems),
            'user_settings': _compare('user_settings', settings_fs,
                                      {r.uid: r.document for r in UserSettings.objects.filter(**live)}, problems),
            'user_subcollections': _compare('user_subcollections', other_fs,
                                            {r.path: r.document for r in UserSubDocument.objects.filter(**live)},
                                            problems),
        }
        for collection, model, key, _ in sync.TOP_LEVEL:
            report[collection] = _compare(
                collection, {s.id: encode(s.to_dict() or {}) for s in db.collection(collection).stream()},
                {r.pk: r.document for r in model.objects.filter(**live)}, problems)

        for name, stats in report.items():
            self.stdout.write(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
        for line in problems:
            self.stdout.write(line)
        bad = sum(s['missing'] + s['extra'] + s['different'] for s in report.values())
        if bad:
            raise CommandError(f'Reconcile found {bad} difference(s). Re-run with --apply, '
                               'or check records changed while it ran.')
        self.stdout.write(self.style.SUCCESS('Reconcile OK: user data in PostgreSQL matches Firestore.'))
