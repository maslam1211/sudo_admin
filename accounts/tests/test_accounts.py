"""Phase 4a: user data copied to PostgreSQL without missing anything."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts import sync
from accounts.models import (
    MASTER_POSTGRES, BlockedUser, DailyUsage, FamilyMember, UserProfile, UserSettings, UserSubDocument,
)
from api.tests.fakes import FakeDB

NOW = datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc)


def seed(db):
    db.put('users/u1', {'fullName': 'Asha Mathew', 'contactNumber': '+919800000001', 'emailAddress': 'Asha@X.com',
                        'city': 'Kochi', 'roleId': '2', 'profileComplete': True, 'appPlatform': 'android',
                        'appBuild': 110, 'createdAt': NOW, 'fcmToken': 'tok', 'isOnline': True})
    db.put('users/u1/user-settings/u1', {'enableCall': True, 'enableSms': False, 'showMobileNumber': True})
    db.put('users/u1/product_subscriptions/s1', {'productId': 'pro', 'status': 'active'})
    db.put('users/u1/reward_transactions/t1', {'points': 5})
    db.put('users/u1/vehicles/legacy1/cart/c1', {'item': 'tag'})      # nested two levels down
    db.put('users/u2', {'fullName': 'Bob', 'mobileNumber': '+919800000002'})
    # A user whose own document is gone but whose subcollection remains.
    db.put('users/ghost/user-settings/ghost', {'enableCall': False})
    db.put('blocked_users/b1', {'blockerId': 'u1', 'blockedUserId': 'u2', 'blockedAt': NOW})
    db.put('family_members/f1', {'ownerId': 'u1', 'name': 'Mom', 'contactNumber': '+919800000009', 'createdAt': NOW})
    db.put('daily_usage/u1', {'scans': 3})


class ImportTests(TestCase):
    def setUp(self):
        self.db = FakeDB()
        seed(self.db)

    def test_everything_is_copied_including_unknown_and_nested_subcollections(self):
        stats = sync.import_everything(self.db)
        self.assertEqual(stats['users'], 3)
        p = UserProfile.objects.get(uid='u1')
        self.assertEqual((p.full_name, p.email_address, p.app_build, p.profile_complete),
                         ('Asha Mathew', 'asha@x.com', 110, True))
        self.assertEqual(p.document['fcmToken'], 'tok')            # full document kept
        self.assertEqual(UserProfile.objects.get(uid='u2').contact_number, '+919800000002')
        s = UserSettings.objects.get(uid='u1')
        self.assertEqual((s.enable_call, s.enable_sms, s.enable_chat), (True, False, None))
        self.assertEqual(set(UserSubDocument.objects.values_list('path', flat=True)), {
            'users/u1/product_subscriptions/s1', 'users/u1/reward_transactions/t1',
            'users/u1/vehicles/legacy1/cart/c1'})
        self.assertFalse(UserProfile.objects.filter(uid='ghost').exists())
        self.assertFalse(UserSettings.objects.get(uid='ghost').enable_call)
        self.assertEqual(BlockedUser.objects.get(id='b1').blocked_user_id, 'u2')
        self.assertEqual(FamilyMember.objects.get(id='f1').name, 'Mom')
        self.assertEqual(DailyUsage.objects.get(uid='u1').document, {'scans': 3})

    def test_deletions_are_kept_marked_deleted(self):
        sync.import_everything(self.db)
        del self.db.docs['users/u2']
        del self.db.docs['users/u1/reward_transactions/t1']
        del self.db.docs['family_members/f1']
        sync.import_everything(self.db)
        self.assertIsNotNone(UserProfile.objects.get(uid='u2').deleted_at)
        self.assertEqual(UserProfile.objects.get(uid='u2').full_name, 'Bob')   # data kept
        self.assertIsNotNone(UserSubDocument.objects.get(path='users/u1/reward_transactions/t1').deleted_at)
        self.assertIsNotNone(FamilyMember.objects.get(id='f1').deleted_at)
        self.assertIsNone(UserProfile.objects.get(uid='u1').deleted_at)

    def test_postgres_mastered_profile_is_never_overwritten(self):
        sync.import_everything(self.db)
        UserProfile.objects.filter(uid='u1').update(master=MASTER_POSTGRES, full_name='Asha M')
        self.db.docs['users/u1']['fullName'] = 'stale'
        del self.db.docs['users/u1']
        sync.import_everything(self.db)
        row = UserProfile.objects.get(uid='u1')
        self.assertEqual((row.full_name, row.deleted_at), ('Asha M', None))

    def test_reconcile_command(self):
        out = io.StringIO()
        with mock.patch('api.management.commands.migrate_accounts.firebase.firestore_db', return_value=self.db):
            call_command('migrate_accounts', '--apply', stdout=out)
            self.assertIn('Reconcile OK', out.getvalue())
            self.assertIn('user_subcollections: firestore=3, postgres=3', out.getvalue())
            self.db.put('users/u1/notes/n1', {'text': 'new subcollection'})
            with self.assertRaises(CommandError):
                call_command('migrate_accounts', stdout=io.StringIO())
            call_command('migrate_accounts', '--apply', stdout=io.StringIO())
            self.assertTrue(UserSubDocument.objects.filter(path='users/u1/notes/n1').exists())
