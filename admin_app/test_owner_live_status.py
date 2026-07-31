"""Tests for owner Live Status helper (mirrors Flutter OwnerLiveStatus)."""

from django.test import SimpleTestCase

from admin_app.owner_live_status import (
    STATUS_AVAILABLE,
    STATUS_BUSY,
    STATUS_CUSTOM,
    STATUS_DO_NOT_DISTURB,
    STATUS_DRIVING,
    STATUS_OUT_OF_STATION,
    STATUS_SLEEPING,
    allows_emergency,
    allows_messaging,
    allows_owner_call,
    live_status_json_payload,
    live_status_service_lines,
    normalize_live_status,
    parse_owner_live_status,
    scanner_message,
    status_label,
)


class OwnerLiveStatusNormalizeTests(SimpleTestCase):
    def test_aliases(self):
        self.assertEqual(normalize_live_status('dnd'), STATUS_DO_NOT_DISTURB)
        self.assertEqual(normalize_live_status('out of station'), STATUS_OUT_OF_STATION)
        self.assertEqual(normalize_live_status('OUT_OF_STATION'), STATUS_OUT_OF_STATION)
        self.assertEqual(normalize_live_status(None), STATUS_AVAILABLE)
        self.assertEqual(normalize_live_status('unknown'), STATUS_AVAILABLE)


class OwnerLiveStatusGatingTests(SimpleTestCase):
    def test_available_allows_all(self):
        self.assertTrue(allows_messaging(STATUS_AVAILABLE))
        self.assertTrue(allows_owner_call(STATUS_AVAILABLE))
        self.assertTrue(allows_emergency(STATUS_AVAILABLE))

    def test_busy_family_blocks_owner_call_only(self):
        for st in (
            STATUS_BUSY,
            STATUS_SLEEPING,
            STATUS_DRIVING,
            STATUS_OUT_OF_STATION,
            STATUS_CUSTOM,
        ):
            self.assertTrue(allows_messaging(st), st)
            self.assertFalse(allows_owner_call(st), st)
            self.assertTrue(allows_emergency(st), st)

    def test_dnd_blocks_messaging_and_owner_call(self):
        self.assertFalse(allows_messaging(STATUS_DO_NOT_DISTURB))
        self.assertFalse(allows_owner_call(STATUS_DO_NOT_DISTURB))
        self.assertTrue(allows_emergency(STATUS_DO_NOT_DISTURB))


class OwnerLiveStatusParseTests(SimpleTestCase):
    def test_parse_available_defaults(self):
        live = parse_owner_live_status({})
        self.assertEqual(live['status'], STATUS_AVAILABLE)
        self.assertTrue(live['allows_messaging'])
        self.assertTrue(live['allows_owner_call'])
        self.assertIn('available', live['message'].lower())

    def test_parse_custom_text(self):
        live = parse_owner_live_status(
            {
                'liveStatus': 'custom',
                'liveStatusCustomText': 'At the gym',
                'isOnline': True,
            }
        )
        self.assertEqual(live['status'], STATUS_CUSTOM)
        self.assertEqual(live['label'], 'At the gym')
        self.assertEqual(live['custom_text'], 'At the gym')
        self.assertTrue(live['is_online'])
        self.assertFalse(live['allows_owner_call'])

    def test_scanner_messages(self):
        self.assertIn('driving', scanner_message(STATUS_DRIVING).lower())
        self.assertIn('busy', scanner_message(STATUS_BUSY).lower())
        self.assertIn('unavailable', scanner_message(STATUS_DO_NOT_DISTURB).lower())

    def test_service_lines_and_json(self):
        live = parse_owner_live_status({'liveStatus': 'driving'})
        lines = live_status_service_lines(live)
        self.assertTrue(any('voice' in x.lower() for x in lines))
        payload = live_status_json_payload(live)
        self.assertEqual(payload['liveStatus'], STATUS_DRIVING)
        self.assertFalse(payload['allowsOwnerCall'])
        self.assertTrue(payload['allowsMessaging'])

    def test_status_label(self):
        self.assertEqual(status_label(STATUS_BUSY), 'Owner Busy')
        self.assertEqual(status_label(STATUS_CUSTOM, 'Hello'), 'Hello')
