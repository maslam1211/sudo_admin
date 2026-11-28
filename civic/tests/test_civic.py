"""Phase 3: CivicSense read copy in PostgreSQL."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase

from admin_app import civic_admin
from api.tests.fakes import FakeDB
from civic import sync
from civic.models import (
    CivicCampaign, CivicLeaderboardEntry, CivicOwnerAlert, CivicPoints, CivicPointsLedgerEntry, CivicReport,
    CivicReportPrivate,
)

NOW = datetime.now(timezone.utc).replace(microsecond=0)
MONTH = NOW.strftime('%Y-%m')


def seed(db):
    db.put('users/reporter', {'fullName': 'Rita'})
    db.put('civic_reports/r1', {'reportId': 'CS-1', 'reporterUid': 'reporter', 'status': 'submitted',
                                'category': 'footpath_blocking', 'vehicleNumber': 'KL07AB1234',
                                'createdAt': NOW - timedelta(hours=2), 'timeline': []})
    db.put('civic_reports/r2', {'reporterUid': 'reporter', 'status': 'resolved', 'category': 'other',
                                'createdAt': NOW - timedelta(days=3)})
    db.put('civic_reports_private/r1', {'ownerUid': 'owner', 'vehicleId': 'v1', 'matchStatus': 'matched',
                                        'alertId': 'r1', 'createdAt': NOW - timedelta(hours=2)})
    db.put('civic_owner_alerts/r1', {'reportDocId': 'r1', 'ownerUid': 'owner', 'ownerStatus': 'open',
                                     'reportedAt': NOW - timedelta(hours=2)})
    db.put('civic_report_actions/a1', {'reportDocId': 'r1', 'action': 'create', 'at': NOW})
    db.put('civic_awareness/c1', {'title': 'Park right', 'isActive': True, 'publishAt': NOW - timedelta(days=1)})
    db.put('civic_awareness/c2', {'title': 'Later', 'isActive': True, 'publishAt': NOW + timedelta(days=5)})
    db.put('civic_stats/global', {'totalReports': 2, 'resolvedReports': 1})
    db.put('civic_points/reporter', {'total': 25, 'monthKey': MONTH, 'monthPoints': 25, 'level': 'starter',
                                     'leaderboardId': 'lb1', 'showOnLeaderboard': True, 'publicName': 'Rita'})
    db.put('civic_points/reporter/ledger/r2_report_resolved', {'reason': 'report_resolved', 'points': 25,
                                                                'reportDocId': 'r2', 'at': NOW})
    db.put('civic_leaderboard/lb1', {'monthKey': MONTH, 'monthPoints': 25, 'total': 25, 'publicName': 'Rita'})
    db.put('civic_rate_limits/reporter', {'day': 'x', 'count': 1})


class ImportTests(TestCase):
    def setUp(self):
        self.db = FakeDB()
        seed(self.db)

    def test_import_copies_everything_and_keeps_the_privacy_split(self):
        stats = sync.import_everything(self.db)
        self.assertEqual(stats['civic_reports']['imported'], 2)
        self.assertEqual(stats['ledger_entries'], 1)
        report = CivicReport.objects.get(id='r1')
        self.assertEqual((report.reporter_uid, report.status), ('reporter', 'submitted'))
        self.assertNotIn('ownerUid', report.document)          # reporter side never holds owner data
        self.assertEqual(CivicReportPrivate.objects.get(id='r1').owner_uid, 'owner')
        self.assertNotIn('reporterUid', CivicOwnerAlert.objects.get(id='r1').document)
        self.assertEqual(CivicPointsLedgerEntry.objects.get(id='reporter/r2_report_resolved').points, 25)
        self.assertEqual(CivicLeaderboardEntry.objects.get(id='lb1').month_points, 25)

    def test_reconcile_command(self):
        out = io.StringIO()
        with mock.patch('api.management.commands.migrate_civic.firebase.firestore_db', return_value=self.db):
            call_command('migrate_civic', '--apply', stdout=out)
            self.assertIn('Reconcile OK', out.getvalue())
            self.db.docs['civic_reports/r1']['status'] = 'verified'
            with self.assertRaises(CommandError):
                call_command('migrate_civic', stdout=io.StringIO())


class AdminTests(TestCase):
    """Admin pages pass the real Firestore client; here the fake stands in for it."""

    def setUp(self):
        cache.clear()
        self.db = FakeDB()
        seed(self.db)
        for p in (mock.patch.object(civic_admin, '_is_live_firestore', return_value=True),
                  mock.patch.object(civic_admin, '_run_tx', side_effect=lambda db, fn: fn(_Tx()))):
            p.start()
            self.addCleanup(p.stop)

    def test_lists_use_firestore_until_imported(self):
        self.assertEqual(civic_admin.list_reports(self.db, state='all')['counts']['all'], 2)
        self.assertEqual(civic_admin.open_report_count(self.db), 1)

    def test_lists_read_the_copy_after_import(self):
        sync.import_everything(self.db)
        for path in [p for p in self.db.docs if p.startswith(('civic_reports', 'civic_awareness', 'civic_points',
                                                               'civic_leaderboard'))]:
            del self.db.docs[path]   # prove the lists below read PostgreSQL
        listed = civic_admin.list_reports(self.db, state='open')
        self.assertEqual([r['id'] for r in listed['reports']], ['r1'])
        self.assertEqual(listed['reports'][0]['owner_uid'], 'owner')   # private side joined for the admin only
        self.assertEqual(listed['counts']['all'], 2)
        self.assertEqual(civic_admin.open_report_count(self.db), 1)
        self.assertEqual([c['id'] for c in civic_admin.list_campaigns(self.db)], ['c2', 'c1'])
        self.assertEqual([m['uid'] for m in civic_admin.list_members(self.db)], ['reporter'])
        self.assertEqual([r['id'] for r in civic_admin.get_leaderboard(self.db, MONTH)], ['lb1'])

    def test_stats_written_back_count_live_campaigns(self):
        sync.import_everything(self.db)
        self.db.docs['civic_awareness/c2']['publishAt'] = NOW - timedelta(minutes=1)   # now live, copy is older
        self.assertEqual(civic_admin.count_live_campaigns(self.db), 2)
        self.assertEqual(CivicCampaign.objects.count(), 2)

    def test_status_change_reaches_the_copy_at_once(self):
        sync.import_everything(self.db)
        civic_admin.update_report_status(self.db, 'r1', 'verified', '', 'admin@sudotag.com')
        self.assertEqual(CivicReport.objects.get(id='r1').status, 'verified')
        self.assertTrue(CivicPointsLedgerEntry.objects.filter(id='reporter/r1_report_verified').exists())
        self.assertGreater(CivicPoints.objects.get(id='reporter').total, 25)
        civic_admin.update_report_status(self.db, 'r1', 'rejected', 'Not a blocking vehicle', 'admin@sudotag.com')
        self.assertEqual(CivicOwnerAlert.objects.get(id='r1').owner_status, 'resolved')
        self.assertTrue(CivicPointsLedgerEntry.objects.filter(id='reporter/r1_revoke_report_verified').exists())

    def test_campaign_and_points_writes_refresh_the_copy(self):
        sync.import_everything(self.db)
        civic_admin.set_campaign_active(self.db, 'c1', False, 'admin@sudotag.com')
        self.assertFalse(CivicCampaign.objects.get(id='c1').is_active)
        civic_admin.adjust_points(self.db, 'reporter', '-5', 'correction', 'admin@sudotag.com')
        self.assertEqual(CivicPoints.objects.get(id='reporter').total, 20)

    def test_test_fakes_never_switch_to_the_copy(self):
        self.assertFalse(type(self.db).__module__.startswith('google.cloud.firestore'))


class _Tx:
    def set(self, ref, data, merge=False):
        ref.set(data, merge=merge)

    def update(self, ref, data):
        ref.update(data)
