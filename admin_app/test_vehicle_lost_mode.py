"""Tests for vehicle Lost Mode helper (mirrors Flutter Vehicle.isLostMode)."""

from datetime import datetime, timezone

from django.test import SimpleTestCase

from admin_app.vehicle_lost_mode import (
    BADGE_LABEL,
    BANNER_BODY,
    BANNER_TITLE,
    TIP_REASON,
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
