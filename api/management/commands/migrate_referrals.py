"""Phase 3 (referrals): fill PostgreSQL from Firestore and prove it matches.

    python manage.py migrate_referrals            # reconcile only (read-only)
    python manage.py migrate_referrals --apply    # import, then reconcile

Compares referralCodes and referrals document by document, and the
referral fields of every users document, in both directions. Exits non-zero
on any difference. Never writes to Firestore.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api import firebase
from api.mirror import content_hash, encode
from referrals import service
from referrals.models import Referral, ReferralCode, ReferralProfile

from .migrate_phase2 import _compare


def _profile_fields(data: dict) -> dict:
    stats = data.get('referralStats')
    return {
        'referralCode': str(data.get('referralCode') or ''),
        'referredByCode': str(data.get('referredByCode') or ''),
        'referredByUserId': str(data.get('referredByUserId') or ''),
        'referralStats': encode(stats) if isinstance(stats, dict) else None,
    }


class Command(BaseCommand):
    help = 'Import referral data from Firestore and reconcile it with PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        db = firebase.firestore_db()
        if apply:
            self.stdout.write(f'import referrals: {service.import_everything(db)}')

        problems: list[str] = []
        fs = lambda name: {s.id: encode(s.to_dict() or {}) for s in db.collection(name).stream()}
        report = {
            'referral_codes': _compare('referral_codes', fs(service.CODES),
                                       {r.code: r.document for r in ReferralCode.objects.filter(deleted_at__isnull=True)},
                                       problems),
            'referrals': _compare('referrals', fs(service.REFERRALS),
                                  {r.id: r.document for r in Referral.objects.filter(deleted_at__isnull=True)},
                                  problems),
            'user_referral_fields': _compare(
                'user_referral_fields',
                {s.id: _profile_fields(s.to_dict() or {}) for s in db.collection(service.USERS).stream()},
                {p.user_id: {'referralCode': p.referral_code, 'referredByCode': p.referred_by_code,
                             'referredByUserId': p.referred_by_user_id, 'referralStats': p.stats}
                 for p in ReferralProfile.objects.filter(deleted_at__isnull=True)},
                problems),
        }
        for name, stats in report.items():
            self.stdout.write(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
        for line in problems:
            self.stdout.write(line)
        bad = sum(s['missing'] + s['extra'] + s['different'] for s in report.values())
        if bad:
            raise CommandError(f'Reconcile found {bad} difference(s). Re-run with --apply, '
                               'or check records changed while it ran.')
        self.stdout.write(self.style.SUCCESS('Reconcile OK: referral data in PostgreSQL matches Firestore.'))
