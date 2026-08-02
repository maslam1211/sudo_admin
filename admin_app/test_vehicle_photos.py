from django.test import SimpleTestCase

from admin_app.vehicle_photos import (
    MAX_VEHICLE_PHOTOS,
    enrich_vehicle_for_admin,
    parse_photo_urls,
    primary_photo_url,
)


class VehiclePhotosHelpersTests(SimpleTestCase):
    def test_parse_empty(self):
        self.assertEqual(parse_photo_urls(None), [])
        self.assertEqual(parse_photo_urls({}), [])
        self.assertEqual(parse_photo_urls({'photoUrls': 'not-a-list'}), [])

    def test_parse_and_cap(self):
        urls = [f'https://example.com/{i}.jpg' for i in range(8)]
        parsed = parse_photo_urls({'photoUrls': urls})
        self.assertEqual(len(parsed), MAX_VEHICLE_PHOTOS)
        self.assertEqual(parsed[0], 'https://example.com/0.jpg')

    def test_primary_and_enrich(self):
        data = {
            'id': 'v1',
            'photoUrls': [
                'https://res.cloudinary.com/demo/image/upload/a.jpg',
                'https://res.cloudinary.com/demo/image/upload/b.jpg',
            ],
        }
        self.assertEqual(
            primary_photo_url(data),
            'https://res.cloudinary.com/demo/image/upload/a.jpg',
        )
        enriched = enrich_vehicle_for_admin(data)
        self.assertTrue(enriched['hasPhotos'])
        self.assertEqual(enriched['primaryPhotoUrl'], data['photoUrls'][0])
        self.assertEqual(len(enriched['photoUrls']), 2)
