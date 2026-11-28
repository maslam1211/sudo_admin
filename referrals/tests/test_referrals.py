"""Phase 3: referrals on PostgreSQL (port of the referral Cloud Functions)."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import Client, TestCase

from admin_app import referral_service as admin_referrals
from api.tests.fakes import FakeDB, fake_run_transaction
from referrals import service
from referrals.models import Referral, ReferralCode, ReferralProfile

NOW = datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc)


def _verify(token):
    if token.startswith('good-'):
        return {'uid': token[5:], 'phone_number': ''}
    raise ValueError('bad')


class Base(TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.db.put('users/alice', {'fullName': 'Alice Mathew', 'contactNumber': '+919800000001'})
        self.db.put('users/bob', {'fullName': 'Bob Varghese', 'contactNumber': '+919800000002'})
        for p in (
            mock.patch('api.firebase.verify_id_token', side_effect=_verify),
            mock.patch('api.firebase.firestore_db', return_value=self.db),
            mock.patch('api.firebase.run_transaction', side_effect=fake_run_transaction),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.client = Client()

    def call(self, method, path, body=None, uid='alice'):
        extra = {'HTTP_AUTHORIZATION': f'Bearer good-{uid}'} if uid else {}
        if method == 'get':
            return self.client.get(path, **extra)
        return self.client.post(path, data=json.dumps(body or {}), content_type='application/json', **extra)

    def alice_code(self):
        return self.call('post', '/api/v1/referrals/code').json()['referralCode']


class CodeTests(Base):
    def test_normalize_matches_cloud_function(self):
        self.assertEqual(service.normalize_code('  sudo-ab 12 '), 'SUDOAB12')
        self.assertEqual(service.normalize_code(None), '')
        self.assertRegex(service._candidate_code(), r'^SUDO[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$')

    def test_ensure_creates_code_index_and_postgres_rows(self):
        r = self.call('post', '/api/v1/referrals/code')
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        code = body['referralCode']
        self.assertEqual(body['referralLink'], f'https://sudotag.com/r/{code}')
        self.assertEqual(body['stats'], service.empty_stats())
        self.assertEqual(self.db.docs['users/alice']['referralCode'], code)
        index = self.db.docs[f'referralCodes/{code}']
        self.assertEqual((index['userId'], index['userName'], index['isActive']), ('alice', 'Alice Mathew', True))
        self.assertEqual(ReferralCode.objects.get(code=code).user_id, 'alice')
        self.assertEqual(ReferralProfile.objects.get(user_id='alice').referral_code, code)

    def test_ensure_is_idempotent_and_repairs_missing_index(self):
        code = self.alice_code()
        self.assertEqual(self.alice_code(), code)
        del self.db.docs[f'referralCodes/{code}']
        self.assertEqual(self.alice_code(), code)
        self.assertIn(f'referralCodes/{code}', self.db.docs)

    def test_ensure_needs_profile_and_sign_in(self):
        r = self.call('post', '/api/v1/referrals/code', uid='nobody')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['error']['message'], 'Create your profile before requesting a referral code.')
        self.assertEqual(self.call('post', '/api/v1/referrals/code', uid=None).status_code, 401)

    def test_ensure_gives_up_after_collisions(self):
        with mock.patch.object(service, '_candidate_code', return_value='SUDOTAKEN000'):
            self.db.put('referralCodes/SUDOTAKEN000', {'userId': 'x'})
            r = self.call('post', '/api/v1/referrals/code')
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()['error']['code'], 'resource-exhausted')


class ApplyTests(Base):
    def apply(self, code, uid='bob'):
        return self.call('post', '/api/v1/referrals/apply', {'referralCode': code}, uid=uid)

    def test_apply_records_referral_and_updates_both_users(self):
        code = self.alice_code()
        r = self.apply(code.lower())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), {'success': True, 'referralId': 'bob', 'referrerUserId': 'alice',
                                    'referralCode': code, 'status': 'pending'})
        edge = self.db.docs['referrals/bob']
        self.assertEqual((edge['referrerName'], edge['referredUserName'], edge['rewardStatus'], edge['rewardAmount']),
                         ('Alice Mathew', 'Bob Varghese', 'none', 0))
        self.assertEqual(self.db.docs['users/bob']['referredByUserId'], 'alice')
        self.assertEqual(self.db.docs['users/alice']['referralStats'],
                         {'totalReferrals': 1, 'successfulReferrals': 0, 'pendingReferrals': 1, 'rewardsEarned': 0})
        self.assertIsInstance(self.db.docs['users/alice']['referralStats']['totalReferrals'], int)
        row = Referral.objects.get(id='bob')
        self.assertEqual((row.referrer_user_id, row.status), ('alice', 'pending'))
        self.assertEqual(ReferralProfile.objects.get(user_id='alice').total_referrals, 1)
        self.assertEqual(ReferralProfile.objects.get(user_id='bob').referred_by_code, code)

    def test_rejections_use_the_cloud_function_messages(self):
        code = self.alice_code()
        cases = [
            (self.apply('ab'), 400, 'A valid referral code is required.'),
            (self.apply('SUDONOPE1234'), 404, 'This referral code is invalid or inactive.'),
            (self.apply(code, uid='alice'), 400, 'You cannot use your own referral code.'),
            (self.apply(code, uid='ghost'), 400, 'Create your profile before applying a referral code.'),
        ]
        for r, status, message in cases:
            self.assertEqual((r.status_code, r.json()['error']['message']), (status, message))
        self.assertEqual(self.apply(code).status_code, 200)
        r = self.apply(code)
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'already-exists'))
        self.assertEqual(self.db.docs['users/alice']['referralStats']['totalReferrals'], 1)

    def test_inactive_code_and_missing_referrer(self):
        self.db.put('referralCodes/SUDOOFF00000', {'userId': 'alice', 'isActive': False})
        self.assertEqual(self.apply('SUDOOFF00000').status_code, 404)
        self.db.put('referralCodes/SUDOGONE0000', {'userId': 'deleted-user'})
        r = self.apply('SUDOGONE0000')
        self.assertEqual(r.json()['error']['message'], 'Referrer account was not found.')
        self.assertNotIn('referrals/bob', self.db.docs)

    def test_existing_referral_doc_blocks_a_second_one(self):
        code = self.alice_code()
        self.db.put('referrals/bob', {'referrerUserId': 'someone', 'status': 'pending'})
        r = self.apply(code)
        self.assertEqual(r.json()['error']['message'], 'A referral has already been recorded for this account.')


class SuccessTests(Base):
    def test_mark_successful_moves_pending_to_successful_once(self):
        code = self.alice_code()
        self.call('post', '/api/v1/referrals/apply', {'referralCode': code}, uid='bob')
        r = self.call('post', '/api/v1/referrals/mark-successful', uid='bob')
        self.assertEqual(r.json(), {'success': True, 'updated': True, 'referralId': 'bob'})
        self.assertEqual(self.db.docs['referrals/bob']['status'], 'successful')
        self.assertEqual(self.db.docs['users/alice']['referralStats'],
                         {'totalReferrals': 1, 'successfulReferrals': 1, 'pendingReferrals': 0, 'rewardsEarned': 0})
        self.assertEqual(Referral.objects.get(id='bob').status, 'successful')
        self.assertEqual(ReferralProfile.objects.get(user_id='alice').successful_referrals, 1)
        again = self.call('post', '/api/v1/referrals/mark-successful', uid='bob').json()
        self.assertEqual(again['reason'], 'already_successful')

    def test_no_referral(self):
        r = self.call('post', '/api/v1/referrals/mark-successful', uid='bob').json()
        self.assertEqual(r, {'success': True, 'updated': False, 'reason': 'no_referral'})


class ReadTests(Base):
    def test_my_referrals_newest_first_with_stats(self):
        self.db.put('referrals/r1', {'referrerUserId': 'alice', 'referredUserId': 'r1', 'status': 'pending',
                                     'registeredAt': NOW - timedelta(days=2)})
        self.db.put('referrals/r2', {'referrerUserId': 'alice', 'referredUserId': 'r2', 'status': 'successful',
                                     'registeredAt': NOW})
        self.db.put('referrals/r3', {'referrerUserId': 'bob', 'referredUserId': 'r3', 'registeredAt': NOW})
        self.db.docs['users/alice']['referralStats'] = {'totalReferrals': 2, 'successfulReferrals': 1}
        service.import_everything(self.db)
        body = self.call('get', '/api/v1/referrals').json()
        self.assertEqual([r['id'] for r in body['referrals']], ['r2', 'r1'])
        self.assertEqual(body['referrals'][0]['registeredAt'], NOW.isoformat())
        self.assertEqual(body['stats'], {'totalReferrals': 2, 'successfulReferrals': 1,
                                         'pendingReferrals': 0, 'rewardsEarned': 0})

    def test_public_code_lookup_shows_first_name_only(self):
        code = self.alice_code()
        body = self.client.get(f'/api/v1/referral-codes/{code.lower()}').json()
        self.assertEqual(body, {'code': code, 'firstName': 'Alice', 'referralLink': f'https://sudotag.com/r/{code}'})
        self.assertNotIn('+9198', json.dumps(body))
        self.assertEqual(self.client.get('/api/v1/referral-codes/SUDOXXXXXXXX').status_code, 404)


class ImportTests(Base):
    def test_import_picks_up_cloud_function_writes_and_keeps_deleted_rows(self):
        # What onUserCreatedAssignReferralCode / older builds leave in Firestore.
        self.db.docs['users/bob']['referralCode'] = 'SUDOBOB12345'
        self.db.put('referralCodes/SUDOBOB12345', {'userId': 'bob', 'userName': 'Bob', 'isActive': True,
                                                   'createdAt': NOW})
        stats = service.import_everything(self.db)
        self.assertEqual(stats['codes'], {'imported': 1, 'marked_deleted': 0})
        self.assertEqual(stats['profiles']['imported'], 2)
        self.assertEqual(ReferralCode.objects.get(code='SUDOBOB12345').created_at, NOW)
        del self.db.docs['referralCodes/SUDOBOB12345']
        service.import_everything(self.db)
        self.assertIsNotNone(ReferralCode.objects.get(code='SUDOBOB12345').deleted_at)

    def test_reconcile_command(self):
        self.alice_code()
        self.db.put('referrals/r1', {'referrerUserId': 'alice', 'referredUserId': 'r1', 'registeredAt': NOW})
        out = io.StringIO()
        with mock.patch('api.management.commands.migrate_referrals.firebase.firestore_db', return_value=self.db):
            call_command('migrate_referrals', '--apply', stdout=out)
            self.assertIn('Reconcile OK', out.getvalue())
            self.db.docs['users/alice']['referralStats'] = {'totalReferrals': 9}
            with self.assertRaises(CommandError):
                call_command('migrate_referrals', stdout=io.StringIO())


class AdminReadTests(Base):
    def test_admin_uses_firestore_until_imported_then_postgres(self):
        self.db.put('referralCodes/SUDOFS000000', {'userId': 'alice', 'userName': 'Alice'})
        with mock.patch.object(admin_referrals, '_get_db', return_value=self.db):
            self.assertEqual(admin_referrals.lookup_referral_code('sudofs000000')['userId'], 'alice')
            service.import_everything(self.db)
            del self.db.docs['referralCodes/SUDOFS000000']  # PostgreSQL now answers
            self.assertEqual(admin_referrals.lookup_referral_code('SUDOFS000000')['userName'], 'Alice')

    def test_admin_lists_filters_and_ranks_from_postgres(self):
        self.db.put('referrals/r1', {'referrerUserId': 'alice', 'referrerName': 'Alice', 'referredUserId': 'r1',
                                     'status': 'successful', 'registeredAt': NOW})
        self.db.put('referrals/r2', {'referrerUserId': 'alice', 'referredUserId': 'r2', 'status': 'pending',
                                     'registeredAt': NOW - timedelta(days=1)})
        self.db.docs['users/alice']['referralStats'] = {'totalReferrals': 2, 'successfulReferrals': 1}
        service.import_everything(self.db)
        self.assertEqual([r['id'] for r in admin_referrals.fetch_referrals()], ['r1', 'r2'])
        self.assertEqual([r['id'] for r in admin_referrals.fetch_referrals(status='pending')], ['r2'])
        self.assertEqual([r['id'] for r in admin_referrals.fetch_referrals(search='alice')], ['r1', 'r2'])
        self.assertEqual(admin_referrals.get_referral_by_id('r1')['isSuccessful'], True)
        self.assertEqual(admin_referrals.get_user_referral_profile('alice')['referralStats']['totalReferrals'], 2)
        top = admin_referrals.top_referrers_from_users()
        self.assertEqual([u['userId'] for u in top], ['alice'])
