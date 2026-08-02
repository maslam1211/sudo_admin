from django.test import SimpleTestCase

from admin_app.public_vehicle_lookup import (
    extract_qr_id_from_scan,
    normalize_registration,
)


class PublicVehicleLookupHelpersTests(SimpleTestCase):
    def test_normalize_registration(self):
        self.assertEqual(normalize_registration('kl-10 ay 2121'), 'KL10AY2121')

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
        self.assertEqual(extract_qr_id_from_scan('plainQrId99'), 'plainQrId99')
        self.assertIsNone(extract_qr_id_from_scan('bad id'))
