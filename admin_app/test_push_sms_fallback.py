"""A failed push to the vehicle owner falls back to SMS when the owner allows SMS."""
import json
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from admin_app import views

OWNER = {'contactNumber': '9876543210'}
VEHICLE = {'ownerContact': '9876543210'}
META = {'attempt': 1, 'session_ttl_sec': 60, 'session_expires_at': 0}


class PushSmsFallbackTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().post('/x')
        patches = {
            'effective_contact_number': mock.Mock(return_value='9876543210'),
            'scanner_effective_channels_now': mock.Mock(return_value={'sms': True}),
            'scanner_user_app_prefs_from_merged': mock.Mock(return_value={'owner_sms_allowed': True}),
            'scanner_pref_merged_dict': mock.Mock(return_value={}),
            'parse_owner_live_status': mock.Mock(return_value={'allows_messaging': True}),
            'send_vehicle_issue_sms': mock.Mock(return_value={'ok': True}),
            'record_notify_messaging_success': mock.Mock(return_value=META),
        }
        self.mocks = {}
        for name, value in patches.items():
            p = mock.patch.object(views, name, value)
            self.mocks[name] = p.start()
            self.addCleanup(p.stop)

    def call(self):
        return views._push_failed_sms_fallback(
            self.request, 'QR1', VEHICLE, OWNER, 'Your car is blocking mine', 'SenderId mismatch')

    def test_sends_sms_when_push_fails(self):
        res = self.call()
        self.assertIsNotNone(res)
        body = json.loads(res.content)
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['notification_type'], 'sms')
        self.mocks['send_vehicle_issue_sms'].assert_called_once_with(
            digits_10='9876543210', message='Your car is blocking mine')

    def test_respects_owner_sms_opt_out(self):
        self.mocks['scanner_user_app_prefs_from_merged'].return_value = {'owner_sms_allowed': False}
        self.assertIsNone(self.call())
        self.mocks['send_vehicle_issue_sms'].assert_not_called()

    def test_respects_live_status(self):
        self.mocks['parse_owner_live_status'].return_value = {'allows_messaging': False}
        self.assertIsNone(self.call())
        self.mocks['send_vehicle_issue_sms'].assert_not_called()

    def test_no_phone_number(self):
        self.mocks['effective_contact_number'].return_value = ''
        self.assertIsNone(self.call())

    def test_sms_failure_returns_none(self):
        self.mocks['send_vehicle_issue_sms'].return_value = {'ok': False, 'error': 'down'}
        self.assertIsNone(self.call())
        self.mocks['record_notify_messaging_success'].assert_not_called()
