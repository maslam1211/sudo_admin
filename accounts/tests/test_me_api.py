"""Phase 4a: the user's own data through /api/v1/me (write-through to Firestore + PostgreSQL)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest import mock

from django.test import Client, TestCase

from accounts import service
from accounts.models import BlockedUser, FamilyMember, UserProfile, UserSettings
from api.tests.fakes import FakeDB

NOW = datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc)


def _verify(token):
    if token.startswith('good-'):
        return {'uid': token[5:], 'phone_number': ''}
    raise ValueError('bad')


class MeApiTests(TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.db.put('users/u1', {'fullName': 'Asha', 'emailAddress': 'asha@x.com', 'contactNumber': '9800000001',
                                 'roleId': 0, 'mustChangePassword': True, 'fcmToken': 'tok', 'createdAt': NOW,
                                 'mobile_number': '9800000001', 'emergency_contact': '9811111111'})
        self.db.put('users/u2', {'fullName': 'Bob', 'emailAddress': 'bob@x.com'})
        for p in (mock.patch('api.firebase.verify_id_token', side_effect=_verify),
                  mock.patch('api.firebase.firestore_db', return_value=self.db)):
            p.start()
            self.addCleanup(p.stop)
        self.client = Client()

    def call(self, method, path, body=None, uid='u1'):
        extra = {'HTTP_AUTHORIZATION': f'Bearer good-{uid}'} if uid else {}
        if method == 'get':
            return self.client.get(path, **extra)
        return getattr(self.client, method)(path, data=json.dumps(body or {}), content_type='application/json',
                                            **extra)

    def test_needs_sign_in(self):
        self.assertEqual(self.call('get', '/api/v1/me', uid=None).status_code, 401)

    def test_new_user_completes_profile(self):
        r = self.call('post', '/api/v1/me/profile', {'fullName': ' Ravi ', 'emailAddress': 'Ravi@X.com',
                                                     'contactNumber': '+91 98000 00003'}, uid='new')
        self.assertEqual(r.status_code, 200, r.content)
        doc = self.db.docs['users/new']
        self.assertEqual((doc['fullName'], doc['emailAddress'], doc['contactNumber'], doc['profileComplete']),
                         ('Ravi', 'ravi@x.com', '9800000003', True))
        self.assertEqual((doc['roleId'], doc['mustChangePassword'], doc['enableIdCheck']), (0, False, True))
        self.assertIn('createdAt', doc)
        self.assertEqual(r.json()['profile']['fullName'], 'Ravi')
        self.assertEqual(UserProfile.objects.get(uid='new').contact_number, '9800000003')

    def test_email_already_used_by_someone_else(self):
        r = self.call('patch', '/api/v1/me/profile', {'emailAddress': 'BOB@x.com'})
        self.assertEqual(r.status_code, 409)
        self.assertIn('already linked to another SudoTag account', r.json()['error']['message'])
        self.assertEqual(self.call('patch', '/api/v1/me/profile', {'emailAddress': 'asha@x.com'}).status_code, 200)

    def test_edit_changes_only_allowed_fields_and_cleans_aliases(self):
        r = self.call('patch', '/api/v1/me/profile', {
            'fullName': 'Asha M', 'city': 'Kochi', 'contactNumber': '919800000005', 'fullProfile': True,
            'roleId': 9, 'mustChangePassword': False, 'rewardBalance': 1000, 'referralCode': 'HACK'})
        self.assertEqual(r.status_code, 200, r.content)
        doc = self.db.docs['users/u1']
        self.assertEqual((doc['fullName'], doc['city'], doc['contactNumber']), ('Asha M', 'Kochi', '9800000005'))
        self.assertEqual((doc['roleId'], doc['mustChangePassword']), (0, True))     # not changeable here
        self.assertNotIn('rewardBalance', doc)
        self.assertNotIn('referralCode', doc)
        self.assertNotIn('mobile_number', doc)                                     # legacy alias removed
        self.assertEqual(doc['fcmToken'], 'tok')                                   # untouched
        self.assertEqual(UserProfile.objects.get(uid='u1').full_name, 'Asha M')

    def test_safety_fields_set_and_clear(self):
        self.call('patch', '/api/v1/me/profile', {'bloodGroup': 'O+', 'defaultEmergencyContact': '+919822222222'})
        doc = self.db.docs['users/u1']
        self.assertEqual((doc['bloodGroup'], doc['defaultEmergencyContact']), ('O+', '9822222222'))
        self.assertNotIn('emergency_contact', doc)
        self.call('patch', '/api/v1/me/profile', {'bloodGroup': '', 'defaultEmergencyContact': ''})
        self.assertNotIn('bloodGroup', self.db.docs['users/u1'])
        self.assertNotIn('defaultEmergencyContact', self.db.docs['users/u1'])

    def test_live_status(self):
        self.assertEqual(self.call('patch', '/api/v1/me/profile', {'liveStatus': 'custom'}).status_code, 400)
        self.call('patch', '/api/v1/me/profile', {'liveStatus': 'custom', 'liveStatusCustomText': 'At the gym'})
        self.assertEqual(self.db.docs['users/u1']['liveStatusCustomText'], 'At the gym')
        self.call('patch', '/api/v1/me/profile', {'liveStatus': 'driving'})
        doc = self.db.docs['users/u1']
        self.assertEqual(doc['liveStatus'], 'driving')
        self.assertNotIn('liveStatusCustomText', doc)
        self.assertEqual(self.call('patch', '/api/v1/me/profile', {'liveStatus': 'asleep'}).status_code, 400)

    def test_profile_picture_must_be_https(self):
        self.assertEqual(self.call('patch', '/api/v1/me/profile',
                                   {'profilePicture': 'javascript:alert(1)'}).status_code, 400)

    def test_settings_merge_only_sent_toggles(self):
        r = self.call('patch', '/api/v1/me/settings', {'enableSms': False})
        self.assertEqual(r.status_code, 200, r.content)
        s = self.db.docs['users/u1/user-settings/u1']
        self.assertFalse(s['enableSms'])
        self.assertTrue(s['enableChat'])          # defaults written on first save
        self.call('patch', '/api/v1/me/settings', {'enableChat': False})
        s = self.db.docs['users/u1/user-settings/u1']
        self.assertEqual((s['enableSms'], s['enableChat']), (False, False))
        self.assertEqual(UserSettings.objects.get(uid='u1').enable_chat, False)
        self.assertEqual(r.json()['settings']['enableSms'], False)
        self.assertEqual(self.call('patch', '/api/v1/me/settings', {'enableSms': 'no'}).status_code, 400)
        self.assertEqual(self.call('patch', '/api/v1/me/settings', {'isAdmin': True}).status_code, 400)

    def test_password_changed_and_civic_terms(self):
        self.db.docs['users/u1'].update({'adminAddedUser': True, 'admin_added_user': True})
        self.call('post', '/api/v1/me/password-changed')
        self.assertFalse(self.db.docs['users/u1']['mustChangePassword'])
        self.assertTrue(self.db.docs['users/u1']['adminAddedUser'])
        self.call('post', '/api/v1/me/password-changed', {'adminAddedUser': False})
        self.assertFalse(self.db.docs['users/u1']['adminAddedUser'])
        self.assertNotIn('admin_added_user', self.db.docs['users/u1'])
        self.call('post', '/api/v1/me/civic-terms', {'version': '1.0.0'})
        self.assertEqual(self.db.docs['users/u1']['civicTermsAcceptedVersion'], '1.0.0')

    def test_block_unblock(self):
        self.assertEqual(self.call('post', '/api/v1/me/blocks', {'userId': 'u1'}).status_code, 400)
        self.call('post', '/api/v1/me/blocks', {'userId': 'u2', 'name': 'Bob'})
        self.call('post', '/api/v1/me/blocks', {'userId': 'u2', 'name': 'Bob'})   # idempotent
        blocks = [d for p, d in self.db.docs.items() if p.startswith('blocked_users/')]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['blockerId'], 'u1')
        self.assertEqual([b['blockedUserId'] for b in self.call('get', '/api/v1/me/blocks').json()['blocked']],
                         ['u2'])
        self.call('delete', '/api/v1/me/blocks/u2')
        self.assertFalse(any(p.startswith('blocked_users/') for p in self.db.docs))
        self.assertIsNotNone(BlockedUser.objects.get().deleted_at)
        self.assertEqual(self.call('get', '/api/v1/me/blocks').json()['blocked'], [])

    def test_family_members_are_owner_only(self):
        r = self.call('post', '/api/v1/me/family', {'name': 'Mom', 'relation': 'Mother',
                                                    'contactNumber': '+91 98333 33333'})
        self.assertEqual(r.status_code, 201, r.content)
        member_id = r.json()['id']
        self.assertEqual(self.db.docs[f'family_members/{member_id}']['contactNumber'], '9833333333')
        self.assertEqual(self.call('post', '/api/v1/me/family', {'name': 'X', 'contactNumber': '12'}).status_code,
                         400)
        self.assertEqual(self.call('put', f'/api/v1/me/family/{member_id}', {'name': 'Hack', 'contactNumber':
                                   '9833333333'}, uid='u2').status_code, 404)
        self.call('put', f'/api/v1/me/family/{member_id}', {'name': 'Amma', 'relation': 'Mother',
                                                            'contactNumber': '9833333333'})
        self.assertEqual(self.db.docs[f'family_members/{member_id}']['name'], 'Amma')
        self.assertEqual([m['name'] for m in self.call('get', '/api/v1/me/family').json()['members']], ['Amma'])
        self.assertEqual(self.call('delete', f'/api/v1/me/family/{member_id}', uid='u2').status_code, 404)
        self.call('delete', f'/api/v1/me/family/{member_id}')
        self.assertNotIn(f'family_members/{member_id}', self.db.docs)
        self.assertIsNotNone(FamilyMember.objects.get(id=member_id).deleted_at)

    def test_get_me_reads_postgres_copy(self):
        self.call('patch', '/api/v1/me/profile', {'city': 'Thrissur'})
        body = self.call('get', '/api/v1/me').json()
        self.assertEqual((body['exists'], body['profile']['city']), (True, 'Thrissur'))
        self.assertEqual(body['profile']['createdAt'], NOW.isoformat())
        self.assertTrue(body['settings']['enableCall'])

    def test_verified_phone_is_recorded_at_login(self):
        service.record_verified_phone(self.db, 'u2', '+919800000002')
        self.assertEqual(self.db.docs['users/u2']['contactNumber'], '9800000002')
        self.assertEqual(UserProfile.objects.get(uid='u2').contact_number, '9800000002')
        service.record_verified_phone(self.db, 'u2', 'garbage')
        self.assertEqual(self.db.docs['users/u2']['contactNumber'], '9800000002')
