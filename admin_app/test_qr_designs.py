import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from admin_app import qr_designs
from admin_app.test_civic_sense import FakeDB


def png_upload(w, h, color=(255, 122, 26), fmt='PNG', name='design.png'):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color).save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class FakeRef:
    """Firestore document ref good enough for save_design."""
    def __init__(self, store, doc_id='d1'):
        self.store, self.id = store, doc_id

    def set(self, data):
        self.store[f'qr_designs/{self.id}'] = dict(data)

    def get(self):
        from admin_app.test_civic_sense import FakeDoc
        return FakeDoc(self.store, f'qr_designs/{self.id}').get()


class SaveDB(FakeDB):
    def collection(self, name):
        col = super().collection(name)
        col.document = (lambda doc_id=None, _c=col: FakeRef(self.store) if doc_id is None else type(_c).document(_c, doc_id))
        return col


class ParseBoxTests(SimpleTestCase):
    def test_valid_box(self):
        self.assertEqual(qr_designs.parse_box('0.6', '0.1', '0.3', 2000, 1000), {'x': 0.6, 'y': 0.1, 'size': 0.3})

    def test_box_outside_image(self):
        with self.assertRaises(qr_designs.DesignError):
            qr_designs.parse_box(0.8, 0.1, 0.3, 2000, 1000)  # runs off the right edge
        with self.assertRaises(qr_designs.DesignError):
            qr_designs.parse_box(0.1, 0.5, 0.3, 2000, 1000)  # 600px square from y=500 runs off the bottom

    def test_missing_box(self):
        with self.assertRaises(qr_designs.DesignError):
            qr_designs.parse_box('', None, 'x', 100, 100)

    def test_width_limits(self):
        self.assertEqual(qr_designs.parse_width_mm('', 'multipurpose'), 80.0)
        with self.assertRaises(qr_designs.DesignError):
            qr_designs.parse_width_mm('5', 'user')


class ComposeTests(SimpleTestCase):
    design = {'box': {'x': 0.5, 'y': 0.2, 'size': 0.4}, 'white_backing': True, 'width_mm': 100.0}

    def test_qr_lands_inside_box_on_white(self):
        art = Image.new('RGB', (1000, 600), (255, 122, 26))
        out = qr_designs.compose(art, self.design, 'https://sudotag.com/admin/send-notification/abc/')
        self.assertEqual(out.size, art.size)
        # Outside the box: untouched artwork
        self.assertEqual(out.getpixel((100, 100)), (255, 122, 26))
        # Box corner (quiet zone): white backing
        self.assertEqual(out.getpixel((501, 121)), (255, 255, 255))
        # Inside the box there are dark QR modules and no orange left
        region = out.crop((500, 120, 900, 520))
        colors = {c for _, c in region.getcolors(1_000_000)}
        self.assertIn((0, 0, 0), colors)
        self.assertNotIn((255, 122, 26), colors)

    def test_print_size_and_dpi(self):
        art = Image.new('RGB', (1181, 591))
        self.assertEqual(qr_designs.print_size_mm(self.design, art), (100.0, 50.04))
        self.assertEqual(qr_designs.dpi_for(self.design, art), 300)


class SaveDesignTests(SimpleTestCase):
    def save(self, **kw):
        args = dict(upload=png_upload(1200, 600), name='Diwali', purpose='user', box_raw=('0.6', '0.1', '0.3'),
                    width_mm_raw='100', white_backing=True, admin_email='a@sudotag.com')
        args.update(kw)
        db = SaveDB({})
        with mock.patch.object(qr_designs, '_upload_to_cloudinary', return_value='https://res.cloudinary.com/x/d1.png'):
            return db, qr_designs.save_design(db, **args)

    def test_saves_design(self):
        db, design = self.save()
        self.assertEqual(design['name'], 'Diwali')
        self.assertEqual(design['box'], {'x': 0.6, 'y': 0.1, 'size': 0.3})
        self.assertEqual(db.store['qr_designs/d1']['imageWidth'], 1200)

    def test_rejects_small_image(self):
        with self.assertRaisesMessage(qr_designs.DesignError, 'at least 600px'):
            self.save(upload=png_upload(800, 400))

    def test_rejects_qr_too_small_to_scan(self):
        with self.assertRaisesMessage(qr_designs.DesignError, 'Make the box bigger'):
            self.save(box_raw=('0.1', '0.1', '0.1'))  # 10 mm on a 100 mm sticker

    def test_requires_name_and_purpose(self):
        with self.assertRaises(qr_designs.DesignError):
            self.save(name=' ')
        with self.assertRaises(qr_designs.DesignError):
            self.save(purpose='poster')


class DesignViewTests(SimpleTestCase):
    def test_requires_admin(self):
        response = self.client.post('/admin/qr-designs/save/')
        self.assertEqual(response.status_code, 403)


class GenerateWithDesignTests(SimpleTestCase):
    databases = {'default'}

    def test_generates_into_custom_design_and_pdf_uses_its_size(self):
        session = self.client.session
        session['admin'] = True
        session.save()
        design = {'id': 'd1', 'name': 'Diwali', 'purpose': 'user', 'image_url': 'https://x/d1.png',
                  'box': {'x': 0.6, 'y': 0.1, 'size': 0.3}, 'width_mm': 100.0, 'white_backing': True}
        fake_db = mock.MagicMock()
        with mock.patch('admin_app.views.db', fake_db), \
             mock.patch('admin_app.views.is_generate_qr_otp_verified', return_value=True), \
             mock.patch.object(qr_designs, 'get_design', return_value=design), \
             mock.patch.object(qr_designs, 'list_designs', return_value=[]), \
             mock.patch.object(qr_designs, 'load_design_image', return_value=Image.new('RGB', (1200, 600), 'orange')), \
             mock.patch('admin_app.context_processors.civic_sense_badge', return_value={}):
            response = self.client.post('/admin/generate-qr/', {
                'qr_type': 'user', 'design_mode': 'custom', 'design_id': 'd1', 'count': '2',
            })
            self.assertEqual(response.status_code, 200)
            batch = fake_db.batch.return_value
            self.assertEqual(batch.set.call_count, 2)
            saved = batch.set.call_args_list[0].args[1]
            self.assertEqual(saved['designId'], 'd1')
            self.assertFalse(saved['isAssigned'])
            self.assertContains(response, 'generated with “Diwali”')

            pdf = self.client.get('/admin/download-qr-pdf/')
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        # 100 × 50 mm page = 283.46 × 141.73 pt
        self.assertIn(b'/MediaBox [ 0 0 283.4646 141.7323 ]', pdf.content)


class PhonePhotoTests(SimpleTestCase):
    def test_rotated_phone_jpeg_is_read_upright(self):
        img = Image.new('RGB', (1200, 800), (255, 122, 26))
        exif = img.getexif()
        exif[0x0112] = 6  # "rotate 90° clockwise to display", as phones save portrait shots
        buf = io.BytesIO()
        img.save(buf, format='JPEG', exif=exif)
        upload = SimpleUploadedFile('phone.jpg', buf.getvalue(), content_type='image/jpeg')
        out = qr_designs.read_design_image(upload)
        self.assertEqual(out.size, (800, 1200))  # what the browser shows

    def test_mpo_is_allowed(self):
        self.assertIn('MPO', qr_designs.ALLOWED_FORMATS)

    def test_cloudinary_failure_gives_clear_message(self):
        import cloudinary.exceptions
        from admin_app import qr_design_views
        session = self.client.session
        session['admin'] = True
        session.save()
        with mock.patch.object(qr_designs, 'save_design', side_effect=cloudinary.exceptions.Error('boom')):
            r = self.client.post('/admin/qr-designs/save/', {'design_image': png_upload(1200, 600), 'name': 'x'})
        self.assertEqual(r.status_code, 502)
        self.assertIn('storage', r.json()['error'])

    databases = {'default'}
