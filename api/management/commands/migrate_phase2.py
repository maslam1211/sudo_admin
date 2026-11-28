"""Phase 2: fill PostgreSQL with app config + checkout data and prove it matches.

    python manage.py migrate_phase2              # reconcile only (read-only report)
    python manage.py migrate_phase2 --apply      # import from Firestore, then reconcile

Reconcile compares every record field by field (Firestore document vs the
`document` column), in both directions, and exits non-zero on any
difference. Read-only on Firestore except for re-copying PostgreSQL-mastered
orders that are out of date.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api import firebase
from api.mirror import content_hash, encode
from appconfig import service as appconfig_service
from appconfig.models import AppConfig, AppRelease
from commerce import sync
from commerce.models import CheckoutSettings, Coupon, Order


def _compare(label, firestore_docs: dict, rows: dict, out: list) -> dict:
    """firestore_docs / rows: id -> encoded document."""
    missing = sorted(set(firestore_docs) - set(rows))
    extra = sorted(set(rows) - set(firestore_docs))
    changed = sorted(i for i in set(firestore_docs) & set(rows)
                     if content_hash(firestore_docs[i]) != content_hash(rows[i]))
    for kind, ids in (('missing in PostgreSQL', missing), ('only in PostgreSQL', extra), ('different', changed)):
        for i in ids[:20]:
            out.append(f'  {label}: {kind}: {i}')
    return {'firestore': len(firestore_docs), 'postgres': len(rows),
            'missing': len(missing), 'extra': len(extra), 'different': len(changed)}


class Command(BaseCommand):
    help = 'Import app config and checkout data from Firestore and reconcile it.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        db = firebase.firestore_db()
        if apply:
            self.stdout.write(f'import commerce: {sync.import_everything(db)}')
            self.stdout.write(f'import appconfig: {appconfig_service.import_everything(db)}')

        problems: list[str] = []
        report = {}

        def fs(collection, key=lambda s: s.id):
            return {key(s): encode(s.to_dict() or {}) for s in db.collection(collection).stream()}

        report['settings'] = _compare('settings', fs(sync.SETTINGS_COLLECTION),
                                      {r.id: r.document for r in CheckoutSettings.objects.all()}, problems)
        coupons_fs = {sync.normalize_coupon_code(k): {**v, 'code': sync.normalize_coupon_code(v.get('code')) or
                                                      sync.normalize_coupon_code(k)}
                      for k, v in fs(sync.COUPONS_COLLECTION).items()}
        report['coupons'] = _compare('coupons', coupons_fs,
                                     {r.code: r.document for r in Coupon.objects.filter(deleted_at__isnull=True)},
                                     problems)
        report['orders'] = _compare('orders', fs(sync.ORDERS_COLLECTION),
                                    {r.id: r.document for r in Order.objects.filter(deleted_at__isnull=True)},
                                    problems)
        configs = {}
        releases = {}
        for platform in appconfig_service.PLATFORMS:
            snap = db.collection('appConfig').document(platform).get()
            if snap.exists:
                configs[platform] = encode(snap.to_dict() or {})
            for r in db.collection('appConfig').document(platform).collection('releases').stream():
                releases[r.id] = encode(r.to_dict() or {})
        report['app_config'] = _compare('app_config', configs,
                                        {r.platform: r.document for r in AppConfig.objects.all()}, problems)
        report['app_releases'] = _compare('app_releases', releases,
                                          {r.id: r.document for r in AppRelease.objects.all()}, problems)

        for name, stats in report.items():
            self.stdout.write(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
        for line in problems:
            self.stdout.write(line)
        bad = sum(s['missing'] + s['extra'] + s['different'] for s in report.values())
        if bad:
            raise CommandError(f'Reconcile found {bad} difference(s). Re-run with --apply, '
                               'or check records changed while it ran.')
        self.stdout.write(self.style.SUCCESS('Reconcile OK: PostgreSQL matches Firestore for every record.'))
