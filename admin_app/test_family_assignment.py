"""Tests for family-member assignment routing helpers and call validation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from admin_app.family_assignment import (
    effective_contact_display_name,
    effective_contact_number,
    has_active_family_assignment,
)
from admin_app.scanner_contact_prefs import validate_scanner_call_for_qr


NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


class FamilyAssignmentHelpersTests(SimpleTestCase):
    def test_active_when_contact_set_and_until_null(self):
        vehicle = {
            'assignedFamilyMemberContact': '9876543210',
            'assignedUntil': None,
        }
        self.assertTrue(has_active_family_assignment(vehicle, now=NOW))

    def test_active_when_until_in_future(self):
        vehicle = {
            'assignedFamilyMemberContact': '9876543210',
            'assignedUntil': NOW + timedelta(hours=12),
        }
        self.assertTrue(has_active_family_assignment(vehicle, now=NOW))

    def test_inactive_when_until_expired(self):
        vehicle = {
            'assignedFamilyMemberContact': '9876543210',
            'assignedUntil': NOW - timedelta(minutes=1),
        }
        self.assertFalse(has_active_family_assignment(vehicle, now=NOW))

    def test_inactive_when_contact_empty(self):
        vehicle = {
            'assignedFamilyMemberContact': '  ',
            'assignedUntil': NOW + timedelta(days=1),
        }
        self.assertFalse(has_active_family_assignment(vehicle, now=NOW))

    def test_effective_number_uses_family_when_active(self):
        vehicle = {
            'assignedFamilyMemberContact': '9876543210',
            'assignedFamilyMemberName': 'Rahul',
            'assignedUntil': NOW + timedelta(hours=1),
            'ownerContact': '9000000001',
        }
        user = {'contactNumber': '9000000002'}
        self.assertEqual(
            effective_contact_number(vehicle, user, now=NOW),
            '9876543210',
        )
        self.assertEqual(
            effective_contact_display_name(vehicle, user, now=NOW),
            'Rahul',
        )

    def test_effective_number_falls_back_to_owner_when_expired(self):
        vehicle = {
            'assignedFamilyMemberContact': '9876543210',
            'assignedFamilyMemberName': 'Rahul',
            'assignedUntil': NOW - timedelta(hours=1),
            'ownerContact': '9000000001',
        }
        user = {'contactNumber': '9000000002', 'fullName': 'Owner Name'}
        self.assertEqual(
            effective_contact_number(vehicle, user, now=NOW),
            '9000000001',
        )
        self.assertEqual(
            effective_contact_display_name(vehicle, user, now=NOW),
            'Owner Name',
        )

    def test_effective_number_falls_back_to_user_contact(self):
        vehicle = {
            'assignedFamilyMemberContact': '',
            'ownerContact': '',
        }
        user = {'contactNumber': '9111222333'}
        self.assertEqual(
            effective_contact_number(vehicle, user, now=NOW),
            '9111222333',
        )

    def test_display_name_fallback_family_member(self):
        vehicle = {
            'assignedFamilyMemberContact': '9876543210',
            'assignedFamilyMemberName': '  ',
            'assignedUntil': None,
        }
        self.assertEqual(
            effective_contact_display_name(vehicle, {}, now=NOW),
            'Family member',
        )


def _mock_firestore_chain(
    *,
    qr_data,
    vehicle_data,
    user_data,
):
    """Build a minimal Firestore client mock for validate_scanner_call_for_qr."""
    db = MagicMock()

    qr_doc = MagicMock()
    qr_doc.exists = True
    qr_doc.to_dict.return_value = qr_data

    vehicle_doc = MagicMock()
    vehicle_doc.exists = True
    vehicle_doc.to_dict.return_value = vehicle_data

    user_doc = MagicMock()
    user_doc.exists = True
    user_doc.to_dict.return_value = user_data

    def collection(name):
        col = MagicMock()

        def document(doc_id):
            ref = MagicMock()
            if name == 'qrcodes':
                ref.get.return_value = qr_doc
            elif name == 'vehicles':
                ref.get.return_value = vehicle_doc
            elif name == 'users':
                ref.get.return_value = user_doc
            else:
                missing = MagicMock()
                missing.exists = False
                ref.get.return_value = missing
            return ref

        col.document.side_effect = document
        return col

    db.collection.side_effect = collection
    return db


class ValidateScannerCallFamilyTests(SimpleTestCase):
    def setUp(self):
        self.qr_data = {'isAssigned': True, 'vehicleID': 'veh1'}
        self.vehicle_base = {
            'ownerId': 'owner1',
            'ownerContact': '9000000001',
        }
        self.user_data = {
            'contactNumber': '9000000001',
            'defaultEmergencyContact': '9888777666',
        }

    @patch('admin_app.scanner_contact_prefs.merge_vehicle_scanner_subdocuments')
    @patch('admin_app.scanner_contact_prefs.merge_user_scanner_subdocuments')
    @patch('admin_app.scanner_contact_prefs.scanner_effective_channels_now')
    @patch('admin_app.scanner_contact_prefs.scanner_flags_from_user_doc')
    @patch('admin_app.scanner_contact_prefs.scanner_user_app_prefs_from_merged')
    @patch('admin_app.scanner_contact_prefs.scanner_pref_merged_dict')
    def test_accepts_active_family_assignee(
        self,
        mock_merged,
        mock_prefs,
        mock_flags,
        mock_eff,
        mock_merge_user,
        mock_merge_vehicle,
    ):
        mock_merge_user.side_effect = lambda db, ref, data: data
        mock_merge_vehicle.side_effect = lambda db, ref, data: data
        mock_merged.return_value = {}
        mock_prefs.return_value = {
            'owner_call_allowed': True,
            'emergency_call_allowed': True,
            'owner_sms_allowed': True,
            'push_allowed': True,
        }
        mock_flags.return_value = {
            'voice': True,
            'sms': True,
            'push': True,
            'emergency': True,
            'emergency_voice': True,
        }
        mock_eff.return_value = {
            'voice': True,
            'sms': True,
            'push': True,
            'emergency': True,
            'emergency_voice': True,
        }

        vehicle = {
            **self.vehicle_base,
            'assignedFamilyMemberContact': '9876543210',
            'assignedFamilyMemberName': 'Rahul',
            'assignedUntil': datetime.now(timezone.utc) + timedelta(days=7),
        }
        db = _mock_firestore_chain(
            qr_data=self.qr_data,
            vehicle_data=vehicle,
            user_data=self.user_data,
        )
        err = validate_scanner_call_for_qr(db, 'qr1', '9876543210')
        self.assertIsNone(err)

    @patch('admin_app.scanner_contact_prefs.merge_vehicle_scanner_subdocuments')
    @patch('admin_app.scanner_contact_prefs.merge_user_scanner_subdocuments')
    @patch('admin_app.scanner_contact_prefs.scanner_effective_channels_now')
    @patch('admin_app.scanner_contact_prefs.scanner_flags_from_user_doc')
    @patch('admin_app.scanner_contact_prefs.scanner_user_app_prefs_from_merged')
    @patch('admin_app.scanner_contact_prefs.scanner_pref_merged_dict')
    def test_rejects_expired_family_assignee(
        self,
        mock_merged,
        mock_prefs,
        mock_flags,
        mock_eff,
        mock_merge_user,
        mock_merge_vehicle,
    ):
        mock_merge_user.side_effect = lambda db, ref, data: data
        mock_merge_vehicle.side_effect = lambda db, ref, data: data
        mock_merged.return_value = {}
        mock_prefs.return_value = {
            'owner_call_allowed': True,
            'emergency_call_allowed': True,
            'owner_sms_allowed': True,
            'push_allowed': True,
        }
        mock_flags.return_value = {
            'voice': True,
            'sms': True,
            'push': True,
            'emergency': True,
            'emergency_voice': True,
        }
        mock_eff.return_value = {
            'voice': True,
            'sms': True,
            'push': True,
            'emergency': True,
            'emergency_voice': True,
        }

        vehicle = {
            **self.vehicle_base,
            'assignedFamilyMemberContact': '9876543210',
            'assignedFamilyMemberName': 'Rahul',
            'assignedUntil': datetime.now(timezone.utc) - timedelta(hours=1),
        }
        db = _mock_firestore_chain(
            qr_data=self.qr_data,
            vehicle_data=vehicle,
            user_data=self.user_data,
        )
        err = validate_scanner_call_for_qr(db, 'qr1', '9876543210')
        self.assertEqual(err, 'This number is not authorized for this QR code.')

        # Owner number still allowed after expiry
        err_owner = validate_scanner_call_for_qr(db, 'qr1', '9000000001')
        self.assertIsNone(err_owner)

    @patch('admin_app.scanner_contact_prefs.merge_vehicle_scanner_subdocuments')
    @patch('admin_app.scanner_contact_prefs.merge_user_scanner_subdocuments')
    @patch('admin_app.scanner_contact_prefs.scanner_effective_channels_now')
    @patch('admin_app.scanner_contact_prefs.scanner_flags_from_user_doc')
    @patch('admin_app.scanner_contact_prefs.scanner_user_app_prefs_from_merged')
    @patch('admin_app.scanner_contact_prefs.scanner_pref_merged_dict')
    def test_emergency_still_only_emergency_number(
        self,
        mock_merged,
        mock_prefs,
        mock_flags,
        mock_eff,
        mock_merge_user,
        mock_merge_vehicle,
    ):
        mock_merge_user.side_effect = lambda db, ref, data: data
        mock_merge_vehicle.side_effect = lambda db, ref, data: data
        mock_merged.return_value = {}
        mock_prefs.return_value = {
            'owner_call_allowed': True,
            'emergency_call_allowed': True,
            'owner_sms_allowed': True,
            'push_allowed': True,
        }
        mock_flags.return_value = {
            'voice': True,
            'sms': True,
            'push': True,
            'emergency': True,
            'emergency_voice': True,
        }
        mock_eff.return_value = {
            'voice': True,
            'sms': True,
            'push': True,
            'emergency': True,
            'emergency_voice': True,
        }

        vehicle = {
            **self.vehicle_base,
            'assignedFamilyMemberContact': '9876543210',
            'assignedUntil': datetime.now(timezone.utc) + timedelta(days=1),
        }
        db = _mock_firestore_chain(
            qr_data=self.qr_data,
            vehicle_data=vehicle,
            user_data=self.user_data,
        )
        err = validate_scanner_call_for_qr(db, 'qr1', '9888777666')
        self.assertIsNone(err)
