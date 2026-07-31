"""Tests for vehicle Lost Mode helper (mirrors Flutter Vehicle.isLostMode)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
    approximate_coordinates,
    attempt_lost_mode_auto_push,
    build_sighting_push_body,
    collect_owner_fcm_tokens,
    format_place_label,
    parse_sighting_location,
    parse_vehicle_lost_mode,
)


class _FakeSession(dict):
    modified = False


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


class LostModeLocationTests(SimpleTestCase):
    def test_approximate_coordinates_round(self):
        coords = approximate_coordinates(12.9715987, 77.5945627)
        self.assertEqual(coords, (12.972, 77.595))

    def test_approximate_rejects_invalid(self):
        self.assertIsNone(approximate_coordinates('x', 1))
        self.assertIsNone(approximate_coordinates(100, 0))

    def test_place_label_prefers_human_label(self):
        self.assertEqual(
            format_place_label(12.97, 77.59, 'Koramangala, Bengaluru'),
            'Koramangala, Bengaluru',
        )

    def test_place_label_fallback_coords(self):
        label = format_place_label(12.972, 77.595, None)
        self.assertIn('12.972', label)
        self.assertIn('77.595', label)

    def test_parse_sighting_location(self):
        loc = parse_sighting_location(
            {
                'latitude': 12.9716,
                'longitude': 77.5946,
                'accuracy': 40,
                'place_label': 'Indiranagar, Bengaluru',
            }
        )
        self.assertTrue(loc['has_location'])
        self.assertEqual(loc['place_label'], 'Indiranagar, Bengaluru')
        self.assertEqual(loc['accuracy_m'], 40.0)

    def test_build_push_body_with_place_and_photos(self):
        body = build_sighting_push_body(place_label='Kochi', photo_count=2)
        self.assertIn('Kochi', body)
        self.assertIn('2 photo', body)
        self.assertIn(AUTO_PUSH_BODY.split('.')[0], build_sighting_push_body())


class LostModeAutoPushTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _session_request(self):
        request = self.factory.get('/admin/send-notification/qr1/')
        request.session = _FakeSession()
        return request

    def _mock_db(self):
        db = MagicMock()
        doc_ref = MagicMock()
        doc_ref.id = 'sighting1'
        db.collection.return_value.document.return_value = doc_ref
        return db

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
            db=self._mock_db(),
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

    @patch('admin_app.vehicle_lost_mode.upload_sighting_photos', return_value=['https://cdn.example/p1.jpg'])
    def test_dedupe_skips_second_send(self, _upload):
        request = self._session_request()
        send_fn = MagicMock(return_value={'success_count': 1, 'message_id': 'm1'})
        vehicle = {
            'isLostMode': True,
            'ownerId': 'u1',
            'fcmToken': 'tok',
        }
        first = attempt_lost_mode_auto_push(
            request=request,
            db=self._mock_db(),
            qr_id='qr1',
            vehicle_id='v1',
            vehicle_data=vehicle,
            user_data={},
            user_ref=None,
            vehicle_ref=None,
            push_capable=True,
            send_push_fn=send_fn,
            location_payload={
                'latitude': 12.97,
                'longitude': 77.59,
                'place_label': 'Bengaluru',
            },
            photos_raw=['data:image/jpeg;base64,aaaa'],
        )
        self.assertTrue(first['sent'])
        self.assertTrue(has_lost_mode_auto_push_sent(request, 'qr1'))
        self.assertEqual(first['photo_count'], 1)
        self.assertIn('Bengaluru', first['notice'])
        send_fn.assert_called_once()
        kwargs = send_fn.call_args.kwargs
        self.assertEqual(kwargs['title'], AUTO_PUSH_TITLE)
        self.assertIn('Bengaluru', kwargs['body'])
        self.assertEqual(kwargs['data'].get('lostMode'), 'true')
        self.assertEqual(kwargs['data'].get('photoCount'), '1')

        second = attempt_lost_mode_auto_push(
            request=request,
            db=self._mock_db(),
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
            db=self._mock_db(),
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
