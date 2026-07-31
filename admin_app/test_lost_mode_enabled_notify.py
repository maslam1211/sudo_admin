from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from admin_app.lost_mode_enabled_notify import (
    build_lost_mode_enabled_sms_body,
    notify_owner_lost_mode_enabled,
)


class LostModeEnabledNotifyTests(SimpleTestCase):
    def test_sms_body_includes_plate(self):
        body = build_lost_mode_enabled_sms_body(
            registration_number='ka01ab1234',
            vehicle_name='My Bike',
        )
        self.assertIn('KA01AB1234', body)
        self.assertIn('Lost Mode is now ON', body)
        self.assertLessEqual(len(body), 200)

    @patch('admin_app.lost_mode_enabled_notify.store_inbox_notification')
    @patch('admin_app.lost_mode_enabled_notify.send_vehicle_issue_sms')
    def test_sends_existing_msg91_sms_and_logs(self, sms_fn, inbox_fn):
        sms_fn.return_value = {
            'ok': True,
            'api': {'status': 'success', 'hasError': False},
        }
        inbox_fn.return_value = {'notification_id': 'n1', 'delivery_id': 'd1'}

        history_ref = MagicMock()
        history_ref.id = 'h1'
        db = MagicMock()
        db.collection.return_value.document.return_value = history_ref

        vehicle = {
            'ownerId': 'u1',
            'ownerContact': '9876543210',
            'registrationNumber': 'KL07X9999',
            'isLostMode': True,
        }
        result = notify_owner_lost_mode_enabled(
            db,
            vehicle_id='v1',
            vehicle_data=vehicle,
            user_data={'contactNumber': '9876543210'},
        )
        self.assertTrue(result['ok'])
        self.assertTrue(result['sms_sent'])
        sms_fn.assert_called_once()
        kwargs = sms_fn.call_args.kwargs
        self.assertEqual(kwargs['digits_10'], '9876543210')
        self.assertIn('Lost Mode is now ON', kwargs['message'])
        inbox_fn.assert_called_once()
        history_ref.set.assert_called_once()
        self.assertEqual(history_ref.set.call_args.args[0]['status'], 'sent')
        self.assertEqual(history_ref.set.call_args.args[0]['channel'], 'sms')

    @patch('admin_app.lost_mode_enabled_notify.store_inbox_notification')
    @patch('admin_app.lost_mode_enabled_notify.send_vehicle_issue_sms')
    def test_client_already_sent_skips_msg91(self, sms_fn, inbox_fn):
        inbox_fn.return_value = {'notification_id': 'n2', 'delivery_id': 'd2'}
        history_ref = MagicMock()
        history_ref.id = 'h3'
        db = MagicMock()
        db.collection.return_value.document.return_value = history_ref

        result = notify_owner_lost_mode_enabled(
            db,
            vehicle_id='v1',
            vehicle_data={
                'ownerId': 'u1',
                'ownerContact': '9876543210',
                'registrationNumber': 'KL01A1',
            },
            user_data={},
            client_sms_sent=True,
            sms_body_override='Lost Mode is now ON for KL01A1.',
        )
        self.assertTrue(result['sms_sent'])
        sms_fn.assert_not_called()
        self.assertEqual(
            history_ref.set.call_args.args[0]['msg91'].get('source'),
            'client_sms_service',
        )

    @patch('admin_app.lost_mode_enabled_notify.send_vehicle_issue_sms')
    def test_skips_when_no_phone(self, sms_fn):
        history_ref = MagicMock()
        history_ref.id = 'h2'
        db = MagicMock()
        db.collection.return_value.document.return_value = history_ref

        result = notify_owner_lost_mode_enabled(
            db,
            vehicle_id='v1',
            vehicle_data={'ownerId': 'u1', 'ownerContact': ''},
            user_data={'contactNumber': ''},
        )
        self.assertFalse(result['sms_sent'])
        self.assertEqual(result['skipped_reason'], 'no_phone')
        sms_fn.assert_not_called()
        self.assertEqual(history_ref.set.call_args.args[0]['status'], 'failed')
