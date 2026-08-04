from django.test import SimpleTestCase

from admin_app.public_vehicle_lookup import (
    activate_url_for_qr,
    extract_qr_id_from_scan,
    normalize_registration,
    notify_final_url_for_qr,
    plate_ocr_variants,
)


class PublicVehicleLookupHelpersTests(SimpleTestCase):
    def test_normalize_registration(self):
        self.assertEqual(normalize_registration('kl-10 ay 2121'), 'KL10AY2121')

    def test_plate_ocr_variants_include_confusion_swaps(self):
        variants = plate_ocr_variants('KL1OAY2121')
        self.assertIn('KL1OAY2121', variants)
        self.assertIn('KL10AY2121', variants)

    def test_extract_qr_from_url(self):
        self.assertEqual(
            extract_qr_id_from_scan(
                'https://sudotag.com/admin/send-notification/abc123XYZ/'
            ),
            'abc123XYZ',
        )
        self.assertEqual(
            extract_qr_id_from_scan(
                'https://sudotag.com/admin/send-notification-final/qr99'
            ),
            'qr99',
        )
        self.assertEqual(
            extract_qr_id_from_scan(
                'https://sudotag.com/admin/activate-id/plainActivate1/'
            ),
            'plainActivate1',
        )
        self.assertEqual(extract_qr_id_from_scan('plainQrId99'), 'plainQrId99')
        self.assertIsNone(extract_qr_id_from_scan('bad id'))

    def test_activate_and_notify_urls(self):
        self.assertTrue(
            activate_url_for_qr('abc').endswith('/admin/activate-id/abc/')
        )
        self.assertTrue(
            notify_final_url_for_qr('abc').endswith(
                '/admin/send-notification-final/abc/'
            )
        )
