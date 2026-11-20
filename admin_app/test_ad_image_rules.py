import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from admin_app.ad_image_rules import AD_IMAGE_RULES, validate_ad_image


def make_image(width, height, fmt='PNG', name='ad.png'):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), (200, 30, 30)).save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')


class ValidateAdImageTests(SimpleTestCase):
    def test_recommended_size_passes_for_every_type(self):
        for ad_type, rules in AD_IMAGE_RULES.items():
            with self.subTest(ad_type=ad_type):
                self.assertIsNone(validate_ad_image(ad_type, make_image(rules['width'], rules['height'])))

    def test_wrong_ratio_is_allowed(self):
        # Shape is only a warning in the browser; the server accepts it.
        self.assertIsNone(validate_ad_image('popup', make_image(1200, 1200, 'JPEG', 'a.jpg')))

    def test_too_small_is_rejected(self):
        error = validate_ad_image('banner', make_image(400, 200))
        self.assertIn('too small', error)
        self.assertIn('800×400', error)

    def test_too_large_file_is_rejected(self):
        upload = make_image(1200, 600)
        upload.size = AD_IMAGE_RULES['banner']['max_bytes'] + 1
        self.assertIn('5.0 MB or smaller', validate_ad_image('banner', upload))

    def test_non_image_is_rejected(self):
        upload = SimpleUploadedFile('ad.png', b'not an image', content_type='image/png')
        self.assertIn('not a readable image', validate_ad_image('popup', upload))

    def test_unsupported_format_is_rejected(self):
        self.assertIn('not supported', validate_ad_image('popup', make_image(1080, 1350, 'BMP', 'a.bmp')))

    def test_unknown_type_is_rejected(self):
        self.assertEqual(validate_ad_image('video', make_image(1200, 600)), 'Unknown ad type.')

    def test_file_is_rewound_for_upload(self):
        upload = make_image(1200, 600)
        validate_ad_image('banner', upload)
        self.assertEqual(upload.tell(), 0)
