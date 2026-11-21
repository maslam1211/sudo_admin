"""Tests for the Partner Programme admin (partner_service.py / partner_views.py).

In-memory Firestore fake; transactions run inline. The admin only records
decisions — wallet changes are made by Cloud Functions and tested there.
"""
from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from firebase_admin import firestore

from admin_app import partner_service as svc


class Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Ref:
    def __init__(self, db, path):
        self.db, self.path = db, path
        self.id = path.split('/')[-1]

    def get(self, transaction=None):
        return Snap(self.id, self.db.store.get(self.path))

    def update(self, data):
        cur = dict(self.db.store[self.path])
        for k, v in data.items():
            if v is firestore.DELETE_FIELD:
                cur.pop(k, None)
            elif v is firestore.SERVER_TIMESTAMP:
                cur[k] = 'now'
            else:
                cur[k] = v
        self.db.store[self.path] = cur

    def set(self, data, merge=False):
        base = dict(self.db.store.get(self.path) or {}) if merge else {}
        base.update({k: ('now' if v is firestore.SERVER_TIMESTAMP else v) for k, v in data.items()})
        self.db.store[self.path] = base

    def collection(self, name):
        return Coll(self.db, f'{self.path}/{name}')


class Coll:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, doc_id):
        return Ref(self.db, f'{self.path}/{doc_id}')

    def add(self, data):
        self.db.added.append((self.path, data))


class FakeDb:
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.added = []

    def collection(self, name):
        return Coll(self, name)


class Tx:
    def update(self, ref, data):
        ref.update(data)


def run_inline(db, fn):
    return fn(Tx())


class ConfigFormTests(SimpleTestCase):
    def form(self, **over):
        base = {
            'enabled': 'on', 'commissionPerTag': '111', 'holdDays': '7', 'minWithdrawal': '500',
            'targetDays': '', 'starter_name': 'Starter', 'starter_tags': '10', 'starter_bonus': '1250',
            'growth_name': 'Growth', 'growth_tags': '50', 'growth_bonus': '7500',
            'premium_name': 'Premium', 'premium_tags': '100', 'premium_bonus': '20000',
        }
        base.update(over)
        return base

    def test_valid_form_matches_proposal(self):
        cfg = svc.parse_config_form(self.form())
        self.assertEqual(cfg['commissionPerTag'], 111)
        self.assertIsNone(cfg['targetDays'])
        self.assertEqual([t['tags'] for t in cfg['targets']], [10, 50, 100])
        self.assertEqual(cfg['targets'][0]['bonus'], 1250)
        self.assertTrue(cfg['enabled'])

    def test_rejects_bad_values(self):
        for over in ({'commissionPerTag': '0'}, {'holdDays': '120'}, {'minWithdrawal': '-1'},
                     {'targetDays': '0'}, {'growth_tags': '10'}, {'starter_bonus': '-5'}):
            with self.assertRaises(svc.PartnerAdminError, msg=str(over)):
                svc.parse_config_form(self.form(**over))

    def test_disabled_when_unchecked(self):
        form = self.form()
        form.pop('enabled')
        self.assertFalse(svc.parse_config_form(form)['enabled'])


class PartnerDecisionTests(SimpleTestCase):
    def test_approve_pending(self):
        db = FakeDb({'partners/u1': {'status': 'pending'}})
        self.assertEqual(svc.decide_partner('u1', 'approve', 'admin', db=db), 'approved')
        self.assertEqual(db.store['partners/u1']['status'], 'approved')
        self.assertEqual(db.added[0][0], 'partner_admin_audit')

    def test_reject_needs_reason(self):
        db = FakeDb({'partners/u1': {'status': 'pending'}})
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_partner('u1', 'reject', 'admin', reason='', db=db)
        svc.decide_partner('u1', 'reject', 'admin', reason='Incomplete details', db=db)
        self.assertEqual(db.store['partners/u1']['rejectReason'], 'Incomplete details')

    def test_invalid_transitions(self):
        db = FakeDb({'partners/u1': {'status': 'approved'}})
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_partner('u1', 'approve', 'admin', db=db)
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_partner('u1', 'reactivate', 'admin', db=db)
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_partner('missing', 'approve', 'admin', db=db)

    def test_suspend_and_reactivate(self):
        db = FakeDb({'partners/u1': {'status': 'approved'}})
        svc.decide_partner('u1', 'suspend', 'admin', reason='Fraud check', db=db)
        self.assertEqual(db.store['partners/u1']['status'], 'suspended')
        svc.decide_partner('u1', 'reactivate', 'admin', db=db)
        self.assertEqual(db.store['partners/u1']['status'], 'approved')


class WithdrawalDecisionTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(svc, '_run_tx', side_effect=run_inline)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_mark_paid_requires_utr(self):
        db = FakeDb({'partnerWithdrawals/w1': {'status': 'requested', 'amount': 2000}})
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_withdrawal('w1', 'paid', 'admin', utr='', db=db)
        svc.decide_withdrawal('w1', 'paid', 'admin', utr='UTR998877', db=db)
        self.assertEqual(db.store['partnerWithdrawals/w1']['status'], 'paid')
        self.assertEqual(db.store['partnerWithdrawals/w1']['utr'], 'UTR998877')
        # Admin never touches the amount or a wallet.
        self.assertEqual(db.store['partnerWithdrawals/w1']['amount'], 2000)
        self.assertFalse(any(k.startswith('partners/') for k in db.store))

    def test_cannot_decide_twice(self):
        db = FakeDb({'partnerWithdrawals/w1': {'status': 'paid'}})
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_withdrawal('w1', 'rejected', 'admin', reason='Too late', db=db)

    def test_reject_needs_reason(self):
        db = FakeDb({'partnerWithdrawals/w1': {'status': 'requested'}})
        with self.assertRaises(svc.PartnerAdminError):
            svc.decide_withdrawal('w1', 'rejected', 'admin', reason='no', db=db)
        svc.decide_withdrawal('w1', 'rejected', 'admin', reason='Name mismatch', db=db)
        self.assertEqual(db.store['partnerWithdrawals/w1']['rejectReason'], 'Name mismatch')


class CommissionReversalTests(SimpleTestCase):
    def test_requests_reversal_only(self):
        db = FakeDb({'partnerCommissions/o1': {'status': 'available', 'amount': 222}})
        svc.request_commission_reversal('o1', 'Fraud check', 'admin', db=db)
        doc = db.store['partnerCommissions/o1']
        self.assertEqual(doc['adminAction'], 'reverse')
        self.assertEqual(doc['status'], 'available')  # Cloud Function reverses it

    def test_already_reversed(self):
        db = FakeDb({'partnerCommissions/o1': {'status': 'reversed'}})
        with self.assertRaises(svc.PartnerAdminError):
            svc.request_commission_reversal('o1', 'Again please', 'admin', db=db)


class ReferralCookieTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.db = FakeDb({'partnerCodes/SUDO1001': {'uid': 'u1', 'active': True},
                          'partnerCodes/SUDO1002': {'uid': 'u2', 'active': False}})

    def test_active_code_is_remembered(self):
        req = self.rf.get('/', {'ref': 'sudo1001'})
        resp = svc.remember_ref(req, HttpResponse(), db=self.db)
        self.assertEqual(resp.cookies[svc.REF_COOKIE].value, 'SUDO1001')

    def test_inactive_or_bad_code_is_ignored(self):
        for ref in ('SUDO1002', 'x', ''):
            resp = svc.remember_ref(self.rf.get('/', {'ref': ref}), HttpResponse(), db=self.db)
            self.assertNotIn(svc.REF_COOKIE, resp.cookies, ref)

    def test_current_ref_prefers_url(self):
        req = self.rf.get('/buy/', {'ref': 'SUDO1003'})
        req.COOKIES[svc.REF_COOKIE] = 'SUDO1001'
        self.assertEqual(svc.current_ref(req), 'SUDO1003')
        req2 = self.rf.get('/buy/')
        req2.COOKIES[svc.REF_COOKIE] = 'SUDO1001'
        self.assertEqual(svc.current_ref(req2), 'SUDO1001')


class PartnerPageRenderTests(SimpleTestCase):
    """Every tab renders (template compiles, partials resolve)."""

    partner = {'uid': 'u1', 'partner_id': 'SUDO1001', 'name': 'Arun', 'phone': '9876543210',
               'city': 'Kochi', 'status': 'approved', 'applied': '', 'approved': '', 'reject_reason': '',
               'payout_ready': True, 'payout_display': 'arun@okhdfc', 'available': 2360, 'pending': 0,
               'on_hold': 0, 'paid': 0, 'lifetime': 2360, 'verified_tags': 10, 'pending_tags': 0,
               'orders': 5, 'target': 'Starter 10/10 (completed)', 'completed_targets': 'starter'}
    withdrawal = {'id': 'w1', 'partner_uid': 'u1', 'partner_id': 'SUDO1001', 'partner_name': 'Arun',
                  'amount': 2000, 'status': 'requested', 'applied_status': 'requested', 'utr': '',
                  'reject_reason': '', 'requested': '', 'decided': '', 'method': 'upi',
                  'upi': 'arun@okhdfc', 'account_name': '', 'account_number': '', 'ifsc': '', 'display': ''}
    commission = {'order_id': 'o1', 'partner_uid': 'u1', 'partner_id': 'SUDO1001', 'status': 'approved',
                  'amount': 222, 'quantity': 2, 'source': 'website', 'created': '', 'available_at': '',
                  'reversed_reason': '', 'reverse_requested': False}

    def get(self, tab, **extra):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from admin_app import partner_views
        req = RequestFactory().get('/partners/', {'tab': tab, **extra})
        req.session = SessionStore()
        req.session['admin'] = True
        req._messages = FallbackStorage(req)
        with mock.patch.multiple(
            svc,
            summary=mock.Mock(return_value={'applications': 1, 'partners': 1, 'withdrawals': 1}),
            list_partners=mock.Mock(return_value=[self.partner]),
            list_withdrawals=mock.Mock(return_value=[self.withdrawal]),
            list_commissions=mock.Mock(return_value=[self.commission]),
            load_config=mock.Mock(return_value=svc.DEFAULT_CONFIG),
            partner_detail=mock.Mock(return_value={
                'partner': self.partner, 'payout': {'method': 'upi', 'upiId': 'arun@okhdfc'},
                'ledger': [{'type': 'commission', 'amount': 222, 'note': '2 tags', 'ref': 'o1', 'created': ''}],
                'commissions': [self.commission], 'withdrawals': [self.withdrawal]}),
        ):
            return partner_views.manage_partners(req)

    def test_all_tabs_render(self):
        for tab, extra, expect in (
            ('applications', {}, 'Approve'),
            ('partners', {}, 'SUDO1001'),
            ('withdrawals', {}, 'Mark paid'),
            ('commissions', {}, 'In hold'),
            ('settings', {}, 'Commission per tag'),
            ('partner', {'uid': 'u1'}, 'Ledger'),
        ):
            resp = self.get(tab, **extra)
            self.assertEqual(resp.status_code, 200, tab)
            self.assertIn(expect, resp.content.decode(), tab)

    def test_requires_admin(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from admin_app import partner_views
        req = RequestFactory().get('/partners/')
        req.session = SessionStore()
        req._messages = FallbackStorage(req)
        resp = partner_views.manage_partners(req)
        self.assertEqual(resp.status_code, 302)


class PartnerExportTests(SimpleTestCase):
    def test_csv_export_and_formula_guard(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from admin_app import partner_views
        row = dict(PartnerPageRenderTests.partner, name='=HYPERLINK("x")')
        req = RequestFactory().get('/partners/', {'export': 'partners'})
        req.session = SessionStore()
        req.session['admin'] = True
        req._messages = FallbackStorage(req)
        with mock.patch.object(svc, 'list_partners', return_value=[row]):
            resp = partner_views.manage_partners(req)
        body = resp.content.decode('utf-8-sig')
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('SUDO1001', body)
        self.assertIn("'=HYPERLINK", body)
        self.assertEqual(partner_views._safe_cell('-222'), '-222')
