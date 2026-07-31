from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from admin_app.msg91_vehicle_sms import send_vehicle_issue_sms


class SendVehicleIssueSmsTests(SimpleTestCase):
    def test_rejects_invalid_phone(self):
        result = send_vehicle_issue_sms(digits_10='123', message='hi')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'invalid_phone')

    @override_settings(MSG91_AUTH_KEY='test-key')
    @patch('admin_app.msg91_vehicle_sms.requests.post')
    def test_sends_campaign_payload(self, post_fn):
        post_fn.return_value = MagicMock(
            status_code=200,
            content=b'{"status":"success","hasError":false}',
            text='{"status":"success","hasError":false}',
            json=lambda: {'status': 'success', 'hasError': False},
        )
        result = send_vehicle_issue_sms(
            digits_10='9876543210',
            message='Lost Mode tip',
        )
        self.assertTrue(result['ok'])
        kwargs = post_fn.call_args.kwargs
        self.assertEqual(kwargs['headers']['authkey'], 'test-key')
        payload = kwargs['json']
        mobile = payload['data']['sendTo'][0]['to'][0]['mobiles']
        self.assertEqual(mobile, '919876543210')
        value = payload['data']['sendTo'][0]['to'][0]['variables']['var']['value']
        self.assertEqual(value, 'Lost Mode tip')
        self.assertEqual(
            payload['data']['sendTo'][0]['to'][0]['variables']['var']['type'],
            'text',
        )

    @override_settings(MSG91_AUTH_KEY='test-key')
    @patch('admin_app.msg91_vehicle_sms.requests.post')
    def test_ok_when_status_omitted_but_no_error(self, post_fn):
        post_fn.return_value = MagicMock(
            status_code=200,
            content=b'{"hasError":false}',
            text='{"hasError":false}',
            json=lambda: {'hasError': False},
        )
        result = send_vehicle_issue_sms(digits_10='9876543210', message='x')
        self.assertTrue(result['ok'])
