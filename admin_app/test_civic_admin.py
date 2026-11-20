"""Tests for the CivicSense admin (civic_admin.py / civic_admin_views.py).

Uses an in-memory Firestore fake. Transactions run inline via a patched
`_run_tx`, and the Firestore sentinels (SERVER_TIMESTAMP, ArrayUnion,
Increment) are applied the way the server would.
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from firebase_admin import firestore

from admin_app import civic_admin as ca

NOW = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)


def _apply(existing, data):
    out = dict(existing or {})
    for key, value in data.items():
        if value is firestore.SERVER_TIMESTAMP:
            out[key] = NOW
        elif isinstance(value, firestore.ArrayUnion):
            cur = list(out.get(key) or [])
            for v in value.values:
                if v not in cur:
                    cur.append(v)
            out[key] = cur
        elif isinstance(value, firestore.Increment):
            out[key] = (out.get(key) or 0) + value.value
        else:
            out[key] = value
    return out


class Snap:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Doc:
    def __init__(self, store, path):
        self.store, self.path = store, path
        self.id = path.split('/')[-1]

    def get(self, transaction=None):
        return Snap(self, self.store.get(self.path))

    def set(self, data, merge=False):
        self.store[self.path] = _apply(self.store.get(self.path) if merge else {}, data)

    def update(self, data):
        if self.path not in self.store:
            raise KeyError(self.path)
        self.store[self.path] = _apply(self.store[self.path], data)

    def delete(self):
        self.store.pop(self.path, None)

    def collection(self, name):
        return Coll(self.store, f'{self.path}/{name}')


class Coll:
    _auto = 0

    def __init__(self, store, path, filters=None, order=None, lim=None):
        self.store, self.path = store, path
        self.filters, self.order, self.lim = filters or [], order, lim

    def document(self, doc_id=None):
        if doc_id is None:
            Coll._auto += 1
            doc_id = f'auto{Coll._auto}'
        return Doc(self.store, f'{self.path}/{doc_id}')

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return None, ref

    def where(self, filter=None):
        return Coll(self.store, self.path, self.filters + [filter], self.order, self.lim)

    def order_by(self, field, direction=None):
        return Coll(self.store, self.path, self.filters, (field, direction), self.lim)

    def limit(self, n):
        return Coll(self.store, self.path, self.filters, self.order, n)

    def stream(self):
        prefix = self.path + '/'
        rows = []
        for path, data in list(self.store.items()):
            rest = path[len(prefix):]
            if not path.startswith(prefix) or '/' in rest:
                continue
            if all(data.get(f.field_path) == f.value for f in self.filters if f.op_string == '=='):
                rows.append(Snap(Doc(self.store, path), data))
        if self.order:
            field, direction = self.order
            rows.sort(key=lambda s: (s.to_dict().get(field) is None, s.to_dict().get(field) or 0),
                      reverse=direction == firestore.Query.DESCENDING)
        return iter(rows[: self.lim] if self.lim else rows)

    def count(self):
        raise NotImplementedError  # exercise the stream fallback


class DB:
    def __init__(self, store):
        self.store = store

    def collection(self, name):
        return Coll(self.store, name)


class Tx:
    def set(self, ref, data, merge=False):
        ref.set(data, merge=merge)

    def update(self, ref, data):
        ref.update(data)


def run_inline(db, fn):
    return fn(Tx())


def make_store():
    return {
        'users/rep': {'fullName': 'Asha Menon', 'emailAddress': 'asha@example.com'},
        'users/own': {'fullName': 'Ravi K', 'contactNumber': '9000000000'},
        'vehicles/v1': {'registrationNumber': 'KL07AB1234', 'ownerId': 'own'},
        'civic_reports/r1': {
            'reportId': 'CS-AAAAAA', 'reporterUid': 'rep', 'category': 'driveway_blocking',
            'description': 'Blocking my gate', 'vehicleNumber': 'KL07AB1234',
            'vehicleNumberMasked': 'KL07••••34', 'location': {'lat': 10.0, 'lng': 76.3, 'accuracyM': 8},
            'address': 'MG Road, Kochi', 'evidencePaths': ['civic_evidence/rep/req1/a.jpg'],
            'status': 'submitted', 'timeline': [{'status': 'submitted', 'at': NOW, 'note': None}],
            'createdAt': NOW - timedelta(hours=2),
            'evidenceDeleteAfter': NOW + timedelta(days=30),
        },
        'civic_reports_private/r1': {
            'reportId': 'CS-AAAAAA', 'reporterUid': 'rep', 'vehicleId': 'v1', 'ownerUid': 'own',
            'alertId': 'r1', 'matchStatus': 'matched', 'ownerNotificationStatus': 'sent',
            'ownerStatus': 'new', 'abuseSuspected': False, 'disputed': False, 'createdAt': NOW,
        },
        'civic_owner_alerts/r1': {'reportDocId': 'r1', 'ownerUid': 'own', 'ownerStatus': 'new'},
        'civic_reports/r2': {
            'reportId': 'CS-BBBBBB', 'reporterUid': 'rep', 'category': 'emergency_access',
            'status': 'verified', 'timeline': [], 'createdAt': NOW - timedelta(days=1),
        },
        'civic_reports_private/r2': {'matchStatus': 'none', 'abuseSuspected': True, 'disputed': True,
                                     'disputeReason': 'Not my car'},
        'civic_reports/r3': {'reportId': 'CS-CCCCCC', 'reporterUid': 'x', 'category': 'other',
                             'status': 'withdrawn', 'createdAt': NOW - timedelta(days=3)},
    }


class Base(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.store = make_store()
        self.db = DB(self.store)
        patches = [
            mock.patch.object(ca, '_run_tx', side_effect=run_inline),
            mock.patch.object(ca, '_now', return_value=NOW),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def ledger(self, uid):
        prefix = f'civic_points/{uid}/ledger/'
        return {k[len(prefix):]: v for k, v in self.store.items() if k.startswith(prefix)}

    def admin_logs(self):
        return [v for k, v in self.store.items() if k.startswith('civic_admin_logs/')]


class PureRuleTests(SimpleTestCase):
    def test_transitions_match_backend(self):
        self.assertTrue(ca.can_transition('submitted', 'verified'))
        self.assertTrue(ca.can_transition('verified', 'resolved'))
        self.assertTrue(ca.can_transition('rejected', 'under_review'))
        self.assertFalse(ca.can_transition('verified', 'submitted'))
        self.assertFalse(ca.can_transition('resolved', 'verified'))
        self.assertEqual(ca.allowed_actions('withdrawn'), [])
        self.assertEqual([a['label'] for a in ca.allowed_actions('rejected')], ['Reopen for review'])

    def test_apply_points_cap_and_floor(self):
        nxt, applied = ca.apply_points({'dayKey': '2026-11-20', 'dayPoints': 25, 'total': 25,
                                        'monthKey': '2026-11', 'monthPoints': 25}, 10, NOW)
        self.assertEqual(applied, 5)
        self.assertEqual(nxt['total'], 30)
        self.assertEqual(nxt['level'], 'helper')
        nxt, applied = ca.apply_points({'total': 3}, -10, NOW)
        self.assertEqual((applied, nxt['total']), (-3, 0))

    def test_apply_points_admin_ignores_cap_and_new_month_resets(self):
        state = {'dayKey': '2026-11-20', 'dayPoints': 30, 'total': 40, 'monthKey': '2026-10', 'monthPoints': 40}
        nxt, applied = ca.apply_points(state, 50, NOW, respect_cap=False)
        self.assertEqual(applied, 50)
        self.assertEqual(nxt['monthPoints'], 50)
        self.assertEqual(nxt['dayPoints'], 30)

    def test_clean_text(self):
        self.assertEqual(ca.clean_text('  a\x00b   c  ', 10), 'ab c')
        self.assertIsNone(ca.clean_text('   ', 10))
        self.assertEqual(ca.clean_text('abcdefgh', 4), 'abcd')

    def test_publish_at_is_ist(self):
        self.assertEqual(ca.parse_publish_at('2026-11-20T11:30'), datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc))
        self.assertIsNone(ca.parse_publish_at(''))
        with self.assertRaises(ca.CivicAdminError):
            ca.parse_publish_at('tomorrow')


class ReportListTests(Base):
    def test_counts_filters_and_private_join(self):
        res = ca.list_reports(self.db, state='open')
        self.assertEqual([r['id'] for r in res['reports']], ['r1'])
        self.assertEqual(res['counts']['open'], 1)
        self.assertEqual(res['counts']['disputed'], 1)
        self.assertEqual(res['counts']['flagged'], 1)
        self.assertEqual(res['counts']['closed'], 1)
        self.assertEqual(res['counts']['all'], 3)
        self.assertEqual(res['reports'][0]['owner_uid'], 'own')

    def test_search_by_plate_with_spaces(self):
        res = ca.list_reports(self.db, state='all', query='kl 07 ab')
        self.assertEqual([r['id'] for r in res['reports']], ['r1'])

    def test_open_count_falls_back_to_stream(self):
        self.assertEqual(ca.open_report_count(self.db), 1)

    def test_detail(self):
        d = ca.get_report_detail(self.db, 'r1')
        self.assertEqual(d['owner']['name'], 'Ravi K')
        self.assertEqual(d['reporter']['email'], 'asha@example.com')
        self.assertEqual(d['vehicle']['number'], 'KL07AB1234')
        self.assertEqual(d['alert']['owner_status'], 'new')
        self.assertIsNone(ca.get_report_detail(self.db, 'missing'))


class StatusUpdateTests(Base):
    def test_verify_awards_points_and_logs(self):
        res = ca.update_report_status(self.db, 'r1', 'verified', 'Looks right', 'admin@sudotag.com')
        self.assertEqual(res, {'from': 'submitted', 'to': 'verified'})
        report = self.store['civic_reports/r1']
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['resolutionNote'], 'Looks right')
        self.assertEqual(report['timeline'][-1]['status'], 'verified')
        self.assertEqual(self.ledger('rep')['r1_report_verified']['points'], 5)
        points = self.store['civic_points/rep']
        self.assertEqual(points['total'], 5)
        board = self.store[f"civic_leaderboard/{points['leaderboardId']}"]
        self.assertEqual(board['monthPoints'], 5)
        self.assertIsNone(board['publicName'])
        self.assertEqual(self.admin_logs()[-1]['to'], 'verified')
        # Owner alert untouched on verify.
        self.assertEqual(self.store['civic_owner_alerts/r1']['ownerStatus'], 'new')

    def test_reject_needs_note_then_revokes_and_closes_alert(self):
        ca.update_report_status(self.db, 'r1', 'verified', '', 'a')
        with self.assertRaises(ca.CivicAdminError):
            ca.update_report_status(self.db, 'r1', 'rejected', '  ', 'a')
        ca.update_report_status(self.db, 'r1', 'rejected', 'Wrong vehicle', 'a')
        self.assertEqual(self.store['civic_points/rep']['total'], 0)
        self.assertEqual(self.ledger('rep')['r1_revoke_report_verified']['points'], -5)
        alert = self.store['civic_owner_alerts/r1']
        self.assertEqual((alert['ownerStatus'], alert['closedReason']), ('resolved', 'rejected'))
        self.assertEqual(self.store['civic_reports/r1']['evidenceDeleteAfter'], NOW + timedelta(days=7))

    def test_resolve_bumps_stats_and_reopen_decrements(self):
        ca.update_report_status(self.db, 'r1', 'resolved', '', 'a')
        self.assertEqual(self.store['civic_stats/global']['resolvedReports'], 1)
        self.assertEqual(self.store['civic_points/rep']['total'], 10)
        ca.update_report_status(self.db, 'r1', 'under_review', '', 'a')
        self.assertEqual(self.store['civic_stats/global']['resolvedReports'], 0)
        # Resolving again does not pay twice.
        ca.update_report_status(self.db, 'r1', 'resolved', '', 'a')
        self.assertEqual(self.store['civic_points/rep']['total'], 10)

    def test_flagged_reporter_gets_no_points(self):
        ca.update_report_status(self.db, 'r2', 'resolved', '', 'a')
        self.assertNotIn('civic_points/rep', self.store)

    def test_invalid_transition(self):
        with self.assertRaises(ca.CivicAdminError):
            ca.update_report_status(self.db, 'r3', 'verified', '', 'a')
        with self.assertRaises(ca.CivicAdminError):
            ca.update_report_status(self.db, 'r1', 'bogus', '', 'a')
        with self.assertRaises(ca.CivicAdminError):
            ca.update_report_status(self.db, 'nope', 'verified', '', 'a')

    def test_duplicate_records_dup_of(self):
        ca.update_report_status(self.db, 'r1', 'duplicate', 'Already reported', 'a', dup_of='r9')
        self.assertEqual(self.store['civic_reports/r1']['dupOf'], 'r9')


class FlagAndEvidenceTests(Base):
    def test_flag_unflag_and_dispute(self):
        ca.set_abuse_flag(self.db, 'r1', True, 'a')
        self.assertTrue(self.store['civic_reports_private/r1']['abuseSuspected'])
        ca.set_abuse_flag(self.db, 'r1', False, 'a')
        self.assertFalse(self.store['civic_reports_private/r1']['abuseSuspected'])
        with self.assertRaises(ca.CivicAdminError):
            ca.resolve_dispute(self.db, 'r1', 'a')
        ca.resolve_dispute(self.db, 'r2', 'a')
        self.assertFalse(self.store['civic_reports_private/r2']['disputed'])

    def test_evidence_only_from_report_paths(self):
        bucket = mock.Mock()
        bucket.blob.return_value.download_as_bytes.return_value = b'img'
        bucket.blob.return_value.content_type = 'image/png'
        report = ca.normalize_report('r1', self.store['civic_reports/r1'])
        self.assertEqual(ca.read_evidence(report, 0, bucket=bucket), (b'img', 'image/png'))
        bucket.blob.assert_called_with('civic_evidence/rep/req1/a.jpg')
        with self.assertRaises(ca.CivicAdminError):
            ca.read_evidence(report, 1, bucket=bucket)

    def test_delete_evidence(self):
        bucket = mock.Mock()
        self.assertEqual(ca.delete_evidence_now(self.db, 'r1', 'a', bucket=bucket), 1)
        report = self.store['civic_reports/r1']
        self.assertEqual(report['evidencePaths'], [])
        self.assertTrue(report['evidenceDeleted'])


class StatsTests(Base):
    def test_recount(self):
        self.store['civic_rate_limits/rep'] = {}
        self.store['civic_awareness/c1'] = {'title': 't', 'isActive': True, 'publishAt': NOW - timedelta(days=1)}
        values = ca.recount_stats(self.db)
        self.assertEqual(values, {'totalReports': 3, 'resolvedReports': 0, 'ownerAcknowledgements': 0,
                                  'activeReporters': 1, 'activeCampaigns': 1})


class CampaignTests(Base):
    def test_create_validate_and_stat(self):
        with self.assertRaises(ca.CivicAdminError):
            ca.save_campaign(self.db, None, {'title': 'x', 'description': 'y', 'link_url': 'http://a'}, 'a')
        cid = ca.save_campaign(self.db, None, {'title': 'Gate', 'description': 'Keep gates clear',
                                               'category': 'parking_tips', 'is_active': True}, 'a')
        doc = self.store[f'civic_awareness/{cid}']
        self.assertEqual(doc['publishAt'], NOW)  # the app orders by publishAt
        self.assertEqual(doc['createdBy'], 'a')
        self.assertEqual(self.store['civic_stats/global']['activeCampaigns'], 1)

        ca.save_campaign(self.db, None, {'title': 'Later', 'description': 'd', 'is_active': True,
                                         'publish_at': '2027-01-01T09:00'}, 'a')
        self.assertEqual(self.store['civic_stats/global']['activeCampaigns'], 1)

        ca.set_campaign_active(self.db, cid, False, 'a')
        self.assertEqual(self.store['civic_stats/global']['activeCampaigns'], 0)
        ca.delete_campaign(self.db, cid)
        self.assertNotIn(f'civic_awareness/{cid}', self.store)

    def test_bad_category_falls_back(self):
        cid = ca.save_campaign(self.db, None, {'title': 't', 'description': 'd', 'category': 'evil'}, 'a')
        self.assertEqual(self.store[f'civic_awareness/{cid}']['category'], 'general')
        self.assertFalse(self.store[f'civic_awareness/{cid}']['isActive'])


class PointsAdminTests(Base):
    def test_adjust(self):
        self.assertEqual(ca.adjust_points(self.db, 'rep', '40', 'Bonus for campaign', 'a'), 40)
        self.assertEqual(self.store['civic_points/rep']['level'], 'helper')
        self.assertEqual(ca.adjust_points(self.db, 'rep', '-100', 'Correction', 'a'), -40)
        self.assertEqual(self.store['civic_points/rep']['total'], 0)
        rows = [v for v in self.ledger('rep').values() if v['reason'] == 'admin_adjustment']
        self.assertEqual(len(rows), 2)
        for bad in ('0', 'abc', '9999'):
            with self.assertRaises(ca.CivicAdminError):
                ca.adjust_points(self.db, 'rep', bad, 'x', 'a')
        with self.assertRaises(ca.CivicAdminError):
            ca.adjust_points(self.db, 'rep', '5', '', 'a')
        with self.assertRaises(ca.CivicAdminError):
            ca.adjust_points(self.db, 'ghost', '5', 'x', 'a')

    def test_hide_name(self):
        self.store['civic_points/rep'] = {'total': 10, 'monthKey': '2026-11', 'monthPoints': 10,
                                          'showOnLeaderboard': True, 'publicName': 'Asha M.',
                                          'leaderboardId': 'lb1'}
        self.store['civic_leaderboard/lb1'] = {'publicName': 'Asha M.', 'monthKey': '2026-11', 'monthPoints': 10}
        ca.hide_public_name(self.db, 'rep', 'a')
        self.assertFalse(self.store['civic_points/rep']['showOnLeaderboard'])
        self.assertTrue(self.store['civic_points/rep']['nameHiddenByAdmin'])
        self.assertIsNone(self.store['civic_leaderboard/lb1']['publicName'])
        self.assertEqual(self.store['civic_leaderboard/lb1']['monthPoints'], 10)

    def test_member_and_leaderboard(self):
        ca.update_report_status(self.db, 'r1', 'verified', '', 'a')
        members = ca.list_members(self.db, query='asha')
        self.assertEqual([m['uid'] for m in members], ['rep'])
        member = ca.get_member(self.db, 'rep')
        self.assertEqual(member['ledger'][0]['label'], 'Report verified')
        self.assertEqual(len(member['reports']), 2)
        board = ca.get_leaderboard(self.db, '2026-11')
        self.assertEqual(board[0]['name'], 'SudoTag member')


class ViewTests(TestCase):
    """Every page renders and every form posts, against the fake store."""

    def setUp(self):
        cache.clear()
        self.store = make_store()
        self.db = DB(self.store)
        patches = [
            mock.patch('admin_app.civic_admin_views._db', return_value=self.db),
            mock.patch.object(ca, '_run_tx', side_effect=run_inline),
            mock.patch.object(ca, 'open_report_count', return_value=1),
            mock.patch('admin_app.civic_sense.open_report_count', return_value=0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        session = self.client.session
        session['admin'] = True
        session['email'] = 'admin@sudotag.com'
        session.save()

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get('/admin/civic-reports/').status_code, 302)
        self.assertEqual(self.client.get('/admin/civic-reports/r1/evidence/0/').status_code, 403)

    def test_pages_render(self):
        for url in ('/admin/civic-reports/', '/admin/civic-reports/?state=all&q=KL07', '/admin/civic-reports/?state=disputed',
                    '/admin/civic-reports/r1/', '/admin/civic-reports/r2/', '/admin/civic-reports/r3/',
                    '/admin/civic-awareness/', '/admin/civic-awareness/new/', '/admin/civic-points/', '/admin/civic-points/rep/'):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200, url)
        self.assertContains(self.client.get('/admin/civic-reports/r1/'), 'Verify report')
        self.assertContains(self.client.get('/admin/civic-reports/r2/'), 'Owner dispute')
        self.assertContains(self.client.get('/admin/civic-reports/'), 'Vehicle Reports')
        self.assertEqual(self.client.get('/admin/civic-reports/missing/').status_code, 404)

    def test_status_post(self):
        res = self.client.post('/admin/civic-reports/r1/status/', {'status': 'verified', 'note': 'ok'})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.store['civic_reports/r1']['status'], 'verified')
        self.assertEqual(self.store['civic_reports/r1']['reviewedBy'], 'admin@sudotag.com')
        res = self.client.post('/admin/civic-reports/r1/status/', {'status': 'verified'}, follow=True)
        self.assertContains(res, 'cannot be moved')

    def test_campaign_flow(self):
        res = self.client.post('/admin/civic-awareness/new/', {'title': 'Gate', 'description': 'Keep clear',
                                                         'category': 'road_safety', 'is_active': 'on',
                                                         'publish_at': ''})
        self.assertEqual(res.status_code, 302)
        cid = next(k.split('/')[1] for k in self.store if k.startswith('civic_awareness/'))
        self.assertEqual(self.client.get(f'/admin/civic-awareness/{cid}/edit/').status_code, 200)
        self.client.post(f'/admin/civic-awareness/{cid}/action/', {'action': 'hide'})
        self.assertFalse(self.store[f'civic_awareness/{cid}']['isActive'])

    def test_member_adjust(self):
        self.client.post('/admin/civic-points/rep/action/', {'action': 'adjust', 'points': '7', 'reason': 'Thanks'})
        self.assertEqual(self.store['civic_points/rep']['total'], 7)
