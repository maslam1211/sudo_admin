"""Email-OTP activation: OTP endpoints, account detection, and multi-vehicle linking."""
import datetime
import json
import re
from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from firebase_admin import auth as fb_auth

from admin_app import activation_email_otp as email_otp
from admin_app.models import ActivationEmailOtp
from admin_app.test_activation_and_admin_access import _FakeDBMixin, verify_email_in_session


def _code_from_outbox():
    return re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)


class EmailOtpEndpointTests(_FakeDBMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fake.store['qrcodes'] = {'QR1': {'isAssigned': False}}
        self.send_url = reverse('activate_id_email_send', args=['QR1'])
        self.verify_url = reverse('activate_id_email_verify', args=['QR1'])
        p = patch(
            'admin_app.views.auth.get_user_by_email',
            side_effect=fb_auth.UserNotFoundError('none'),
        )
        self.get_user_by_email = p.start()
        self.addCleanup(p.stop)

    def _send(self, email='Asha@Example.com'):
        return self.client.post(self.send_url, json.dumps({'email': email}),
                                content_type='application/json')

    def _verify(self, otp, email='Asha@Example.com'):
        return self.client.post(self.verify_url, json.dumps({'email': email, 'otp': otp}),
                                content_type='application/json')

    def test_send_emails_six_digit_code_and_masks_address(self):
        res = self._send()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['masked_email'], 'as***@example.com')
        self.assertEqual(mail.outbox[-1].to, ['asha@example.com'])
        self.assertRegex(_code_from_outbox(), r'^\d{6}$')
        # Only an HMAC is stored, never the code.
        self.assertNotEqual(ActivationEmailOtp.objects.get().code_hash, _code_from_outbox())

    def test_send_does_not_reveal_whether_account_exists(self):
        self.fake.store['users'] = {'U9': {'emailAddress': 'asha@example.com'}}
        res = self._send()
        self.assertNotIn('account', res.json())
        self.get_user_by_email.assert_not_called()

    def test_send_rejects_invalid_email_and_activated_qr(self):
        self.assertEqual(self._send('not-an-email').status_code, 400)
        self.fake.store['qrcodes']['QR1']['isAssigned'] = True
        res = self._send()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error_type'], 'already_activated')

    def test_resend_within_cooldown_is_rate_limited(self):
        self._send()
        res = self._send()
        self.assertEqual(res.status_code, 429)
        self.assertGreater(res.json()['retry_after'], 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_hourly_cap_per_email(self):
        for _ in range(email_otp.MAX_SENDS_PER_EMAIL_PER_HOUR):
            self._send()
            ActivationEmailOtp.objects.update(
                created_at=timezone.now() - datetime.timedelta(seconds=120),
            )
        res = self._send()
        self.assertEqual(res.status_code, 429)

    def test_failed_delivery_does_not_lock_out_retry(self):
        with patch('admin_app.activation_email_otp.send_mail', side_effect=OSError('smtp')):
            self.assertEqual(self._send().status_code, 503)
        self.assertEqual(self._send().status_code, 200)

    def test_correct_code_for_new_email_reports_new_account(self):
        self._send()
        res = self._verify(_code_from_outbox())
        self.assertEqual(res.status_code, 200, res.content)
        account = res.json()['account']
        self.assertFalse(account['exists'])
        self.assertTrue(account['needsDetails'])
        self.assertEqual(email_otp.verified_email(
            SimpleNamespace(session=self.client.session), 'QR1')[0], 'asha@example.com')

    def test_correct_code_for_existing_account_reports_vehicle_count(self):
        self.fake.store['users'] = {'U9': {'emailAddress': 'asha@example.com'}}
        self.fake.store['vehicles'] = {
            'V1': {'ownerId': 'U9', 'registrationNumber': 'KL01AB1234'},
            'V2': {'ownerId': 'U9', 'registrationNumber': 'KL07CD5678'},
            'VX': {'ownerId': 'OTHER', 'registrationNumber': 'KL09ZZ0001'},
        }
        self.get_user_by_email.side_effect = None
        self.get_user_by_email.return_value = SimpleNamespace(uid='U9')
        self._send()
        account = self._verify(_code_from_outbox()).json()['account']
        self.assertTrue(account['exists'])
        self.assertFalse(account['needsDetails'])
        self.assertEqual(account['vehicleCount'], 2)
        self.assertEqual(account['qrId'], 'QR1')

    def test_code_is_single_use(self):
        self._send()
        code = _code_from_outbox()
        self.assertEqual(self._verify(code).status_code, 200)
        self.client.session.flush()
        self.assertEqual(self._verify(code).status_code, 400)

    def test_wrong_guesses_burn_the_code(self):
        self._send()
        code = _code_from_outbox()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(email_otp.MAX_VERIFY_ATTEMPTS):
            self.assertEqual(self._verify(wrong).status_code, 400)
        res = self._verify(code)
        self.assertEqual(res.status_code, 400)
        self.assertIn('new code', res.json()['message'])

    def test_expired_code_is_rejected(self):
        self._send()
        ActivationEmailOtp.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self._verify(_code_from_outbox()).status_code, 400)

    def test_code_is_bound_to_its_qr(self):
        self.fake.store['qrcodes']['QR2'] = {'isAssigned': False}
        self._send()
        res = self.client.post(
            reverse('activate_id_email_verify', args=['QR2']),
            json.dumps({'email': 'asha@example.com', 'otp': _code_from_outbox()}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 400)

    def test_lookup_retry_without_code_needs_prior_verification(self):
        res = self.client.post(self.verify_url, json.dumps({'email': 'asha@example.com'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)


@override_settings(ACTIVATION_EMAILS_SYNC=True)
class ExistingAccountMultiVehicleTests(_FakeDBMixin, TestCase):
    """A verified existing customer adds another vehicle to the same uid."""

    VEHICLE_ONLY = {
        'make': 'Honda',
        'model': 'City',
        'registrationNumber': 'kl 07 cd 9999',
        'vehicleType': 'Car',
        'yearOfManufacturing': '2022',
    }

    def setUp(self):
        super().setUp()
        self.fake.store['qrcodes'] = {'QR3': {'isAssigned': False}}
        self.fake.store['users'] = {'U9': {
            'emailAddress': 'customer@gmail.com',
            'fullName': 'Customer One',
            'contactNumber': '+919876543210',
            'city': 'Kochi',
        }}
        self.fake.store['vehicles'] = {
            'V1': {'ownerId': 'U9', 'registrationNumber': 'KL01AB1234', 'qrCodeId': 'QR1'},
            'V2': {'ownerId': 'U9', 'registrationNumber': 'KL07CD5678', 'qrCodeId': 'QR2'},
        }
        self.before = {k: dict(v) for k, v in self.fake.store['vehicles'].items()}
        for target, kwargs in (
            ('admin_app.views.auth.get_user_by_email', {'return_value': SimpleNamespace(uid='U9')}),
            ('admin_app.views.auth.update_user', {}),
            ('admin_app.views.auth.create_user', {}),
            ('admin_app.views.auth.delete_user', {}),
            ('admin_app.views.create_or_update_firebase_user', {}),
            ('admin_app.views.send_welcome_email_for_id', {}),
            ('admin_app.views.send_vehicle_registration_email', {}),
        ):
            p = patch(target, **kwargs)
            setattr(self, target.rsplit('.', 1)[-1], p.start())
            self.addCleanup(p.stop)
        verify_email_in_session(self.client, 'QR3', 'customer@gmail.com')

    def _post(self, payload):
        return self.client.post(
            reverse('activate_id', args=['QR3']), json.dumps(payload),
            content_type='application/json', HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_third_vehicle_joins_existing_account(self):
        # No owner fields and no phone OTP: they come from the existing profile.
        res = self._post(self.VEHICLE_ONLY)
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertFalse(body['is_new_user'])
        self.assertTrue(body['ui_notice']['is_existing_account'])
        self.assertIsNone(body['ui_notice']['account_welcome'])
        self.assertEqual(body['ui_notice']['account_email'], 'customer@gmail.com')
        self.assertEqual(body['ui_notice']['qr_id'], 'QR3')

        self.create_or_update_firebase_user.assert_not_called()
        self.create_user.assert_not_called()
        self.send_welcome_email_for_id.assert_not_called()

        qr = self.fake.store['qrcodes']['QR3']
        self.assertEqual(qr['userID'], 'U9')
        new_vehicle = self.fake.store['vehicles'][qr['vehicleID']]
        self.assertEqual(new_vehicle['ownerId'], 'U9')
        self.assertEqual(new_vehicle['registrationNumber'], 'KL07CD9999')
        self.assertEqual(new_vehicle['ownerFullName'], 'Customer One')
        self.assertEqual(new_vehicle['ownerContact'], '+919876543210')

        user = self.fake.store['users']['U9']
        self.assertEqual(user['vehicleCount'], 3)
        self.assertTrue(user['emailVerified'])
        self.assertEqual(user['fullName'], 'Customer One')
        self.assertEqual(len(self.fake.store['users']), 1)
        for vid, data in self.before.items():
            self.assertEqual(self.fake.store['vehicles'][vid], data)
        self.update_user.assert_called_once_with('U9', email_verified=True)

    def test_verification_is_spent_after_activation(self):
        self.assertEqual(self._post(self.VEHICLE_ONLY).status_code, 200)
        self.assertEqual(email_otp.verified_email(
            SimpleNamespace(session=self.client.session), 'QR3'), (None, None))

    def test_plate_already_on_account_is_refused_without_changes(self):
        res = self._post({**self.VEHICLE_ONLY, 'registrationNumber': 'KL-01-AB-1234'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('registrationNumber', res.json()['errors'])
        self.assertFalse(self.fake.store['qrcodes']['QR3']['isAssigned'])
        self.assertNotIn('vehicleCount', self.fake.store['users']['U9'])

    def test_login_without_profile_gets_profile_under_same_uid(self):
        # e.g. an app sign-up whose profile write failed: keep the login, add the profile.
        self.fake.store['users'] = {}
        self.fake.store['vehicles'] = {}
        with patch('admin_app.views.is_activate_phone_verified', return_value=True):
            res = self._post({**self.VEHICLE_ONLY, 'fullName': 'Customer One',
                              'contactNumber': '+919876543210', 'city': 'Kochi'})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn('U9', self.fake.store['users'])
        self.assertTrue(self.fake.store['users']['U9']['emailVerified'])
        self.assertEqual(self.fake.store['users']['U9']['vehicleCount'], 1)
        self.assertIsNone(res.json()['ui_notice']['account_welcome'])
        self.create_or_update_firebase_user.assert_not_called()

    def test_login_without_profile_still_needs_owner_details(self):
        self.fake.store['users'] = {}
        res = self._post(self.VEHICLE_ONLY)
        self.assertEqual(res.status_code, 400)
        self.assertIn('fullName', res.json()['errors'])

    def test_qr_lost_to_concurrent_activation_leaves_account_untouched(self):
        from admin_app import views
        real_claim = views._activate_id_claim_qr

        def claim_after_other_winner(qr_ref, *args, **kwargs):
            self.fake.store['qrcodes']['QR3']['isAssigned'] = True
            return real_claim(qr_ref, *args, **kwargs)

        with patch('admin_app.views._activate_id_claim_qr', claim_after_other_winner):
            res = self._post(self.VEHICLE_ONLY)
        self.assertEqual(res.status_code, 409)
        self.delete_user.assert_not_called()
        self.assertIn('U9', self.fake.store['users'])
        self.assertNotIn('vehicleCount', self.fake.store['users']['U9'])
        self.assertEqual(len(self.fake.store['vehicles']), 2)


class DummyEmailOtpTests(_FakeDBMixin, TestCase):
    """Local test mode: fixed code, no email, only while DEBUG is on."""

    def setUp(self):
        super().setUp()
        self.fake.store['qrcodes'] = {'QR1': {'isAssigned': False}}
        p = patch(
            'admin_app.views.auth.get_user_by_email',
            side_effect=fb_auth.UserNotFoundError('none'),
        )
        p.start()
        self.addCleanup(p.stop)

    def _send(self):
        return self.client.post(reverse('activate_id_email_send', args=['QR1']),
                                json.dumps({'email': 'asha@example.com'}),
                                content_type='application/json')

    def _verify(self, otp):
        return self.client.post(reverse('activate_id_email_verify', args=['QR1']),
                                json.dumps({'email': 'asha@example.com', 'otp': otp}),
                                content_type='application/json')

    @override_settings(DEBUG=True, ACTIVATION_DUMMY_EMAIL_OTP='123456')
    def test_dummy_code_works_without_email(self):
        res = self._send()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['test_code'], '123456')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self._send().status_code, 200)  # no cooldown in test mode
        self.assertEqual(self._verify('123456').status_code, 200)

    @override_settings(DEBUG=False, ACTIVATION_DUMMY_EMAIL_OTP='123456')
    def test_dummy_code_ignored_when_debug_off(self):
        res = self._send()
        self.assertNotIn('test_code', res.json())
        self.assertEqual(len(mail.outbox), 1)
        real = _code_from_outbox()
        if real != '123456':
            self.assertEqual(self._verify('123456').status_code, 400)
