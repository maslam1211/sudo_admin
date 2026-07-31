"""Tests for vehicle Lost Mode helper (mirrors Flutter Vehicle.isLostMode)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from django.test import RequestFactory, SimpleTestCase

from admin_app.scanner_notify_session_controls import (
    clear_lost_mode_auto_push,
    clear_notify_session_for_rescan,
    has_lost_mode_auto_push_sent,
    mark_lost_mode_auto_push_sent,
)
from admin_app.vehicle_lost_mode import (
    AUTO_PUSH_BODY,
    AUTO_PUSH_TITLE,
    BADGE_LABEL,
    BANNER_BODY,
    BANNER_TITLE,
    TIP_REASON,
    attempt_lost_mode_auto_push,
    collect_owner_fcm_tokens,
    parse_vehicle_lost_mode,
)


class VehicleLostModeParseTests(SimpleTestCase):
    def test_missing_fields_default_off(self):
        lost = parse_vehicle_lost_mode({})
        self.assertFalse(lost['is_lost_mode'])
        self.assertFalse(lost['isLostMode'])
        self.assertIsNone(lost['lost_mode_enabled_at'])
        self.assertEqual(lost['banner_title'], BANNER_TITLE)
        self.assertEqual(lost['badge_label'], BADGE_LABEL)

    def test_none_vehicle_defaults_off(self):
        lost = parse_vehicle_lost_mode(None)
        self.assertFalse(lost['is_lost_mode'])
        self.assertIsNone(lost['lost_mode_enabled_at'])

    def test_explicit_false_clears_timestamp(self):
        lost = parse_vehicle_lost_mode(
            {
                'isLostMode': False,
                'lostModeEnabledAt': datetime(2026, 8, 1, tzinfo=timezone.utc),
            }
        )
        self.assertFalse(lost['is_lost_mode'])
        self.assertIsNone(lost['lost_mode_enabled_at'])

    def test_true_with_datetime(self):
        ts = datetime(2026, 8, 1, 3, 30, tzinfo=timezone.utc)
        lost = parse_vehicle_lost_mode(
            {
                'isLostMode': True,
                'lostModeEnabledAt': ts,
            }
        )
        self.assertTrue(lost['is_lost_mode'])
        self.assertIsNotNone(lost['lost_mode_enabled_at'])
        self.assertIn('2026-08-01', lost['lost_mode_enabled_at'])
        self.assertEqual(lost['banner_body'], BANNER_BODY)
        self.assertEqual(lost['tip_reason'], TIP_REASON)

    def test_string_true_aliases(self):
        for raw in ('true', 'True', '1', 'yes', 'on'):
            lost = parse_vehicle_lost_mode({'isLostMode': raw})
            self.assertTrue(lost['is_lost_mode'], raw)

    def test_null_enabled_at_when_on(self):
        lost = parse_vehicle_lost_mode(
            {'isLostMode': True, 'lostModeEnabledAt': None}
        )
        self.assertTrue(lost['is_lost_mode'])
        self.assertIsNone(lost['lost_mode_enabled_at'])


class _FakeSession(dict):
    modified = False


class LostModeAutoPushTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _session_request(self):
        request = self.factory.get('/admin/send-notification/qr1/')
        request.session = _FakeSession()
        return request

    def test_collect_tokens_dedupes(self):
        tokens = collect_owner_fcm_tokens(
            {'fcmToken': 'tok-a'},
            {'fcmToken': 'tok-a'},
        )
        self.assertEqual(tokens, ['tok-a'])
        tokens2 = collect_owner_fcm_tokens(
            {'fcmToken': 'tok-v'},
            {'fcmToken': 'tok-u'},
        )
        self.assertEqual(tokens2, ['tok-v', 'tok-u'])

    def test_skip_when_not_lost(self):
        request = self._session_request()
        result = attempt_lost_mode_auto_push(
            request=request,
            db=MagicMock(),
            qr_id='qr1',
            vehicle_id='v1',
            vehicle_data={'isLostMode': False, 'ownerId': 'u1', 'fcmToken': 't'},
            user_data={},
            user_ref=None,
            vehicle_ref=None,
            push_capable=True,
            send_push_fn=MagicMock(),
        )
        self.assertFalse(result['sent'])
        self.assertEqual(result['skipped_reason'], 'not_lost_mode')

    def test_dedupe_skips_second_send(self):
        request = self._session_request()
        send_fn = MagicMock(return_value={'success_count': 1, 'message_id': 'm1'})
        vehicle = {
            'isLostMode': True,
            'ownerId': 'u1',
            'fcmToken': 'tok',
        }
        first = attempt_lost_mode_auto_push(
            request=request,
            db=MagicMock(),
            qr_id='qr1',
            vehicle_id='v1',
            vehicle_data=vehicle,
            user_data={},
            user_ref=None,
            vehicle_ref=None,
            push_capable=True,
            send_push_fn=send_fn,
        )
        self.assertTrue(first['sent'])
        self.assertTrue(has_lost_mode_auto_push_sent(request, 'qr1'))
        send_fn.assert_called_once()
        kwargs = send_fn.call_args.kwargs
        self.assertEqual(kwargs['title'], AUTO_PUSH_TITLE)
        self.assertEqual(kwargs['body'], AUTO_PUSH_BODY)
        self.assertEqual(kwargs['data'].get('lostMode'), 'true')

        second = attempt_lost_mode_auto_push(
            request=request,
            db=MagicMock(),
            qr_id='qr1',
            vehicle_id='v1',
            vehicle_data=vehicle,
            user_data={},
            user_ref=None,
            vehicle_ref=None,
            push_capable=True,
            send_push_fn=send_fn,
        )
        self.assertFalse(second['sent'])
        self.assertEqual(second['skipped_reason'], 'already_sent')
        self.assertEqual(send_fn.call_count, 1)

    def test_rescan_clears_dedupe(self):
        request = self._session_request()
        mark_lost_mode_auto_push_sent(request, 'qr1')
        self.assertTrue(has_lost_mode_auto_push_sent(request, 'qr1'))
        clear_notify_session_for_rescan(request, 'qr1')
        self.assertFalse(has_lost_mode_auto_push_sent(request, 'qr1'))
        clear_lost_mode_auto_push(request, 'qr1')  # idempotent

    def test_skip_when_push_not_capable(self):
        request = self._session_request()
        result = attempt_lost_mode_auto_push(
            request=request,
            db=MagicMock(),
            qr_id='qr1',
            vehicle_id='v1',
            vehicle_data={'isLostMode': True, 'ownerId': 'u1', 'fcmToken': 't'},
            user_data={},
            user_ref=None,
            vehicle_ref=None,
            push_capable=False,
            send_push_fn=MagicMock(),
        )
        self.assertEqual(result['skipped_reason'], 'push_unavailable')
