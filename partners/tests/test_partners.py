"""Phase 3: Partner Programme read copy in PostgreSQL (option B — the money
rules stay in the Cloud Functions; nothing here writes a balance)."""

from __future__ import annotations

import copy
import io
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from admin_app import partner_service as svc
from api.tests.fakes import FakeDB
from partners import sync
from partners.models import (
    Partner, PartnerCode, PartnerCommission, PartnerLedgerEntry, PartnerPayout, PartnerSetting, PartnerWithdrawal,
)

NOW = datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc)
WALLET = {'available': 555, 'pending': 111, 'onHold': 500, 'paid': 1000, 'lifetime': 2166}


def seed(db):
    db.put('partnerProgram/config', {'commissionPerTag': 111, 'holdDays': 7})
    db.put('counters/partnerIds', {'next': 1003})
    db.put('partners/p1', {'partnerId': 'SUDO1001', 'name': 'Asha', 'phone': '9800000001', 'city': 'Kochi',
                           'status': 'approved', 'wallet': WALLET, 'appliedAt': NOW - timedelta(days=9)})
    db.put('partners/p2', {'name': 'Ravi', 'status': 'pending', 'appliedAt': NOW})
    db.put('partners/p1/private/payout', {'method': 'upi', 'upiId': 'asha@upi', 'display': 'asha@upi'})
    db.put('partners/p1/ledger/l1', {'type': 'commission', 'amount': 111, 'ref': 'o1', 'createdAt': NOW})
    db.put('partners/p1/ledger/l2', {'type': 'withdrawal_requested', 'amount': -500, 'ref': 'w1', 'createdAt': NOW})
    db.put('partnerCodes/SUDO1001', {'uid': 'p1', 'active': True, 'createdAt': NOW})
    db.put('partnerCommissions/o1', {'partnerUid': 'p1', 'status': 'available', 'amount': 111, 'quantity': 1,
                                     'source': 'order', 'createdAt': NOW - timedelta(days=8)})
    db.put('partnerCommissions/o2', {'partnerUid': 'p1', 'status': 'pending', 'amount': 111, 'quantity': 1,
                                     'createdAt': NOW})
    db.put('partnerWithdrawals/w1', {'partnerUid': 'p1', 'partnerId': 'SUDO1001', 'amount': 500,
                                     'status': 'requested', 'requestedAt': NOW})
    db.put('partnerWithdrawals/w0', {'partnerUid': 'p1', 'amount': 1000, 'status': 'paid',
                                     'requestedAt': NOW - timedelta(days=20), 'utr': 'UTR123456'})
    db.put('partnerActivationClaims/qrcodes_Q1', {'partnerUid': 'p1', 'status': 'booked'})
    db.put('partner_admin_audit/a1', {'kind': 'partner', 'action': 'approve', 'at': NOW})
    db.put('partnerSecrets/p1', {'hash': 'never-copied'})


class ImportTests(TestCase):
    def setUp(self):
        self.db = FakeDB()
        seed(self.db)

    def test_import_copies_every_collection_with_typed_columns(self):
        stats = sync.import_everything(self.db)
        self.assertEqual(stats['partners']['imported'], 2)
        self.assertEqual(stats['ledger_entries'], 2)
        p = Partner.objects.get(uid='p1')
        self.assertEqual((p.partner_id, p.status, p.wallet_available, p.wallet_on_hold, p.wallet_lifetime),
                         ('SUDO1001', 'approved', 555, 500, 2166))
        self.assertEqual(PartnerPayout.objects.get(uid='p1').document['upiId'], 'asha@upi')
        self.assertEqual(PartnerLedgerEntry.objects.get(id='p1/l2').amount, -500)
        self.assertTrue(PartnerCode.objects.get(code='SUDO1001').active)
        self.assertEqual(PartnerCommission.objects.get(id='o1').created_at, NOW - timedelta(days=8))
        self.assertEqual(PartnerSetting.objects.get(path='counters/partnerIds').document, {'next': 1003})
        self.assertFalse(any('never-copied' in str(r.document) for r in Partner.objects.all()))

    def test_removed_documents_are_kept_marked_deleted(self):
        sync.import_everything(self.db)
        del self.db.docs['partners/p1/ledger/l1']
        del self.db.docs['partnerCommissions/o2']
        sync.import_everything(self.db)
        self.assertIsNotNone(PartnerLedgerEntry.objects.get(id='p1/l1').deleted_at)
        self.assertIsNotNone(PartnerCommission.objects.get(id='o2').deleted_at)
        self.assertIsNone(PartnerCommission.objects.get(id='o1').deleted_at)

    def test_reconcile_command(self):
        out = io.StringIO()
        with mock.patch('api.management.commands.migrate_partners.firebase.firestore_db', return_value=self.db):
            call_command('migrate_partners', '--apply', stdout=out)
            self.assertIn('Reconcile OK', out.getvalue())
            self.assertIn('₹2,166', out.getvalue())
            self.db.docs['partners/p1/ledger/l1']['amount'] = 999   # a balance change not yet copied
            with self.assertRaises(CommandError):
                call_command('migrate_partners', stdout=io.StringIO())


class AdminReadTests(TestCase):
    """The real pages call partner_service without a db: they read the copy."""

    def setUp(self):
        self.db = FakeDB()
        seed(self.db)
        for p in (mock.patch.object(svc, '_db', return_value=self.db),
                  mock.patch.object(svc, '_run_tx', side_effect=lambda db, fn: fn(_Tx()))):
            p.start()
            self.addCleanup(p.stop)
        sync.import_everything(self.db)
        self.firestore_before = copy.deepcopy(self.db.docs)

    def test_lists_and_counts_come_from_postgres(self):
        self.db.docs.clear()   # prove nothing below reads Firestore
        self.assertEqual([r['uid'] for r in svc.list_partners(status='pending')], ['p2'])
        self.assertEqual([r['name'] for r in svc.list_partners(query='kochi')], ['Asha'])
        self.assertEqual(svc.list_partners(status='approved')[0]['available'], 555)
        self.assertEqual([r['id'] for r in svc.list_withdrawals()], ['w1'])
        self.assertEqual([r['id'] for r in svc.list_withdrawals(status='', partner_uid='p1')], ['w1', 'w0'])
        self.assertEqual([r['order_id'] for r in svc.list_commissions(partner_uid='p1')], ['o2', 'o1'])
        self.assertEqual(svc.summary(), {'applications': 1, 'partners': 1, 'withdrawals': 1})
        self.assertTrue(svc.is_active_code('sudo1001'))

    def test_new_code_not_yet_copied_is_checked_in_firestore(self):
        self.db.put('partnerCodes/SUDO1002', {'uid': 'p2', 'active': True})
        self.assertTrue(svc.is_active_code('SUDO1002'))
        self.assertFalse(svc.is_active_code('SUDO9999'))

    def test_withdrawal_decision_reaches_postgres_at_once(self):
        svc.decide_withdrawal('w1', 'paid', 'admin@sudotag.com', utr='UTR987654')
        self.assertEqual(self.db.docs['partnerWithdrawals/w1']['status'], 'paid')
        self.assertEqual(PartnerWithdrawal.objects.get(id='w1').status, 'paid')
        self.assertEqual(svc.list_withdrawals(), [])
        # The admin records the decision only; the Cloud Function moves the money.
        self.assertEqual(self.db.docs['partners/p1']['wallet'], WALLET)

    def test_partner_decision_and_reversal_refresh_the_copy(self):
        svc.decide_partner('p2', 'approve', 'admin@sudotag.com')
        self.assertEqual(Partner.objects.get(uid='p2').status, 'approved')
        svc.request_commission_reversal('o2', 'duplicate order', 'admin@sudotag.com')
        self.assertEqual(PartnerCommission.objects.get(id='o2').document['adminAction'], 'reverse')

    def test_settings_save_refreshes_copy(self):
        svc.save_config({'commissionPerTag': 150}, 'admin@sudotag.com')
        self.assertEqual(PartnerSetting.objects.get(path='partnerProgram/config').document['commissionPerTag'], 150)

    def test_detail_page_reads_firestore_live(self):
        self.db.docs['partners/p1']['wallet'] = {**WALLET, 'available': 666}   # changed by a trigger just now
        self.assertEqual(svc.partner_detail('p1')['partner']['available'], 666)


class _Tx:
    def update(self, ref, data):
        ref.update(data)
