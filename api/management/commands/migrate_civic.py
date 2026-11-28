"""Phase 3 (CivicSense, read copy): fill PostgreSQL and prove it matches.

    python manage.py migrate_civic            # reconcile only (read-only)
    python manage.py migrate_civic --apply    # import, then reconcile

Compares every CivicSense collection and every points ledger, record by
record in both directions. Exits non-zero on any difference. Never writes
to Firestore.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api import firebase
from api.mirror import encode
from civic import sync
from civic.models import CivicPointsLedgerEntry

from .migrate_phase2 import _compare


class Command(BaseCommand):
    help = 'Import CivicSense data from Firestore and reconcile it with PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        db = firebase.firestore_db()
        if apply:
            self.stdout.write(f'import civic: {sync.import_everything(db)}')

        problems: list[str] = []
        live = {'deleted_at__isnull': True}
        report = {}
        for table in sync.TABLES:
            report[table.collection] = _compare(
                table.collection,
                {s.id: encode(s.to_dict() or {}) for s in db.collection(table.collection).stream()},
                {r.pk: r.document for r in table.model.objects.filter(**live)}, problems)
        ledger = {}
        for snap in db.collection('civic_points').stream():
            for entry in db.collection('civic_points').document(snap.id).collection('ledger').stream():
                ledger[f'{snap.id}/{entry.id}'] = encode(entry.to_dict() or {})
        report['points_ledger'] = _compare('points_ledger', ledger,
                                           {r.pk: r.document for r in CivicPointsLedgerEntry.objects.filter(**live)},
                                           problems)

        for name, stats in report.items():
            self.stdout.write(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
        for line in problems:
            self.stdout.write(line)
        bad = sum(s['missing'] + s['extra'] + s['different'] for s in report.values())
        if bad:
            raise CommandError(f'Reconcile found {bad} difference(s). Re-run with --apply, '
                               'or check records changed while it ran.')
        self.stdout.write(self.style.SUCCESS('Reconcile OK: CivicSense data in PostgreSQL matches Firestore.'))
