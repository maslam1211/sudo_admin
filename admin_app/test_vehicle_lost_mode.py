"""Tests for vehicle Lost Mode helper (mirrors Flutter Vehicle.isLostMode)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from admin_app.vehicle_lost_mode import (
    AUTO_PUSH_BODY,
    AUTO_PUSH_TITLE,
    BADGE_LABEL,
    BANNER_BODY,
    BANNER_TITLE,
    SPOTTER_LIVE_LOCATION_TITLE,
    SPOTTER_LOCATION_TITLE,
    TIP_REASON,
    approximate_coordinates,
    attempt_lost_mode_auto_push,
    build_lost_mode_sms_message,
    build_sighting_push_body,
    build_spotter_location_notification,
    collect_owner_fcm_tokens,
    format_place_label,
    format_scanned_at_ist,
    google_maps_url,
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
        body = build_sighting_push_body(
            place_label='Kochi',
            photo_count=2,
            scanned_at_display='01 Aug 2026, 04:10 AM IST',
        )
        self.assertIn('Kochi', body)
        self.assertIn('2 photo', body)
        self.assertIn('01 Aug 2026', body)
        self.assertIn('Scanned at', body)

    def test_build_push_body_includes_maps_link(self):
        body = build_sighting_push_body(
            latitude=11.258753,
            longitude=75.780411,
            scanned_at_display='02 Aug 2026, 04:45 PM IST',
        )
        self.assertIn(
            'A person has shared their location while reporting your vehicle.',
            body,
        )
        self.assertIn('View on Google Maps:', body)
        self.assertIn(
            'https://www.google.com/maps?q=11.258753,75.780411',
            body,
        )
        self.assertIn('Shared at: 02 Aug 2026, 04:45 PM IST', body)

    def test_spotter_location_notification_format(self):
        title, body = build_spotter_location_notification(
            latitude=11.258753,
            longitude=75.780411,
            shared_at_display='02 Aug 2026, 4:45 PM',
        )
        self.assertEqual(title, SPOTTER_LOCATION_TITLE)
        self.assertIn('View on Google Maps:', body)
        self.assertIn(
            'https://www.google.com/maps?q=11.258753,75.780411',
            body,
        )
        self.assertIn('Shared at:', body)

    def test_spotter_live_location_notification_format(self):
        title, body = build_spotter_location_notification(
            latitude=11.258753,
            longitude=75.780411,
            shared_at_display='02 Aug 2026, 4:50 PM',
            live_update=True,
        )
        self.assertEqual(title, SPOTTER_LIVE_LOCATION_TITLE)
        self.assertIn('Updated at:', body)
        self.assertIn(
            'https://www.google.com/maps?q=11.258753,75.780411',
            body,
        )

    def test_lost_mode_sms_includes_google_maps_link(self):
        maps = 'https://www.google.com/maps?q=11.258753,75.780411'
        msg = build_lost_mode_sms_message(
            reason='I spotted this vehicle',
            latitude=11.258753,
            longitude=75.780411,
            maps_url=maps,
            shared_at_display='02 Aug 2026, 04:45 PM IST',
        )
        self.assertIn(
            'A person has shared their location while reporting your vehicle',
            msg,
        )
        self.assertIn('View Location:', msg)
        self.assertIn(maps, msg)
        self.assertIn('Shared at', msg)
        self.assertLessEqual(len(msg), 200)
        self.assertEqual(
            google_maps_url(11.258753, 75.780411),
            maps,
        )

    def test_lost_mode_sms_without_coords_is_plain_tip(self):
        msg = build_lost_mode_sms_message(reason='I spotted this vehicle')
        self.assertEqual(msg, 'I spotted this vehicle')
        self.assertNotIn('google.com/maps', msg)

    def test_lost_mode_sms_uses_same_maps_url_as_push(self):
        maps = 'https://www.google.com/maps?q=11.258753,75.780411'
        msg = build_lost_mode_sms_message(
            latitude=11.258753,
            longitude=75.780411,
            maps_url=maps,
        )
        self.assertIn(maps, msg)
        self.assertLessEqual(len(msg), 200)

    def test_parse_sighting_sets_google_maps_url(self):
        loc = parse_sighting_location(
            {'latitude': 11.258753, 'longitude': 75.780411}
        )
        self.assertTrue(loc['has_location'])
        self.assertEqual(
            loc['google_maps_url'],
            'https://www.google.com/maps?q=11.258753,75.780411',
        )

    def test_format_scanned_at_ist(self):
        label = format_scanned_at_ist(
            datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc)
        )
        self.assertIn('IST', label)
        self.assertIn('2026', label)


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

    @patch('admin_app.vehicle_lost_mode.upload_sighting_photos', return_value=[])
    def test_every_scan_sends_again_no_cooldown(self, _upload):
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
                'scanned_at': '2026-08-01T10:00:00+00:00',
            },
            photos_raw=[],
            upload_photos=False,
        )
        self.assertTrue(first['sent'])
        self.assertIn('Google Maps', first['notice'])
        self.assertTrue(first.get('scanned_at_display'))
        self.assertIn('Scanned at', first['notice'])
        kwargs = send_fn.call_args.kwargs
        self.assertEqual(kwargs['title'], SPOTTER_LOCATION_TITLE)
        self.assertIn('View on Google Maps:', kwargs['body'])
        self.assertIn('https://www.google.com/maps?q=', kwargs['body'])
        self.assertIn('Shared at:', kwargs['body'])
        self.assertEqual(kwargs['data'].get('lostMode'), 'true')
        self.assertEqual(
            kwargs['data'].get('googleMapsUrl'),
            first.get('google_maps_url'),
        )
        self.assertTrue(kwargs['data'].get('googleMapsUrl'))
        self.assertEqual(kwargs['data'].get('locationShared'), 'true')

        # No cooldown — second scan also notifies.
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
            location_payload={'scanned_at': '2026-08-01T10:05:00+00:00'},
            upload_photos=False,
        )
        self.assertTrue(second['sent'])
        self.assertEqual(send_fn.call_count, 2)

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
            location_payload={'scanned_at': '2026-08-01T10:00:00+00:00'},
            upload_photos=False,
        )
        self.assertEqual(result['skipped_reason'], 'push_unavailable')
        self.assertFalse(result['sent'])
        # Scan time still prepared so SMS can use the same tip body.
        self.assertTrue(result.get('scanned_at_display'))
        self.assertTrue(result.get('tip_body'))
