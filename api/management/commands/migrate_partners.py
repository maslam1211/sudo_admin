"""Phase 3 (partner programme, read copy): fill PostgreSQL and prove it matches.

    python manage.py migrate_partners            # reconcile only (read-only)
    python manage.py migrate_partners --apply    # import, then reconcile

Compares every partner collection, each partner's payout details and
ledger, and the two settings documents, record by record in both
directions. Exits non-zero on any difference. Never writes to Firestore.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api import firebase
from api.mirror import encode
from partners import sync
from partners.models import Partner, PartnerLedgerEntry, PartnerPayout, PartnerSetting

from .migrate_phase2 import _compare


class Command(BaseCommand):
    help = 'Import Partner Programme data from Firestore and reconcile it with PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        db = firebase.firestore_db()
        if apply:
            self.stdout.write(f'import partners: {sync.import_everything(db)}')

        problems: list[str] = []
        live = {'deleted_at__isnull': True}
        report = {}
        for table in sync.TABLES:
            report[table.collection] = _compare(
                table.collection,
                {s.id: encode(s.to_dict() or {}) for s in db.collection(table.collection).stream()},
                {r.pk: r.document for r in table.model.objects.filter(**live)}, problems)

        settings_fs = {}
        for path in sync.SETTING_PATHS:
            coll, doc_id = path.split('/')
            snap = db.collection(coll).document(doc_id).get()
            if snap.exists:
                settings_fs[path] = encode(snap.to_dict() or {})
        report['settings'] = _compare('settings', settings_fs,
                                      {r.path: r.document for r in PartnerSetting.objects.filter(**live)}, problems)

        payouts, ledger = {}, {}
        for snap in db.collection('partners').stream():
            ref = db.collection('partners').document(snap.id)
            payout = ref.collection('private').document('payout').get()
            if payout.exists:
                payouts[snap.id] = encode(payout.to_dict() or {})
            for entry in ref.collection('ledger').stream():
                ledger[f'{snap.id}/{entry.id}'] = encode(entry.to_dict() or {})
        report['payouts'] = _compare('payouts', payouts,
                                     {r.uid: r.document for r in PartnerPayout.objects.filter(**live)}, problems)
        report['ledger'] = _compare('ledger', ledger,
                                    {r.id: r.document for r in PartnerLedgerEntry.objects.filter(**live)}, problems)

        for name, stats in report.items():
            self.stdout.write(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
        for line in problems:
            self.stdout.write(line)
        bad = sum(s['missing'] + s['extra'] + s['different'] for s in report.values())
        if bad:
            raise CommandError(f'Reconcile found {bad} difference(s). Re-run with --apply, '
                               'or check records changed while it ran.')
        wallets = sum(p.wallet_lifetime for p in Partner.objects.filter(**live))
        self.stdout.write(self.style.SUCCESS(
            f'Reconcile OK: partner data in PostgreSQL matches Firestore (lifetime earnings ₹{wallets:,}).'))
