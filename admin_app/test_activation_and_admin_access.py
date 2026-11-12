"""Web activation (activate-id) and admin access-control regression tests.

Firestore is replaced by a small in-memory fake so the views run end to end
without network access.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from firebase_admin import auth as fb_auth
from firebase_admin import firestore as fb_firestore

from admin_app import views


class _Snap:
    def __init__(self, doc_id, data, ref):
        self.id = doc_id
        self._data = data
        self.reference = ref

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _DocRef:
    def __init__(self, store, coll, doc_id):
        self._store, self._coll, self.id = store, coll, doc_id

    def _docs(self):
        return self._store.setdefault(self._coll, {})

    def get(self, transaction=None):
        data = self._docs().get(self.id)
        return _Snap(self.id, dict(data) if data is not None else None, self)

    def set(self, data):
        self._docs()[self.id] = _clean(dict(data))

    def update(self, data):
        if self.id not in self._docs():
            raise KeyError(f'No document {self._coll}/{self.id}')
        current = self._docs()[self.id]
        for key, value in data.items():
            if value is fb_firestore.DELETE_FIELD:
                current.pop(key, None)
            else:
                current[key] = value

    def delete(self):
        self._docs().pop(self.id, None)


def _clean(data):
    return {k: v for k, v in data.items() if v is not fb_firestore.DELETE_FIELD}


class _Query:
    def __init__(self, store, coll, filters=()):
        self._store, self._coll, self._filters = store, coll, tuple(filters)

    def where(self, filter=None, **_):
        return _Query(self._store, self._coll, self._filters + (filter,))

    def limit(self, _n):
        return self

    def stream(self):
        out = []
        for doc_id, data in list(self._store.get(self._coll, {}).items()):
            if all(data.get(f.field_path) == f.value for f in self._filters):
                out.append(_Snap(doc_id, dict(data), _DocRef(self._store, self._coll, doc_id)))
        return out

    def get(self):
        return self.stream()


class _Collection(_Query):
    def document(self, doc_id):
        return _DocRef(self._store, self._coll, doc_id)


class _Txn:
    def set(self, ref, data):
        ref.set(data)

    def update(self, ref, data):
        ref.update(data)


class FakeDB:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return _Collection(self.store, name)

    def transaction(self):
        return _Txn()


def _passthrough_transactional(fn):
    def wrapper(transaction):
        return fn(transaction)
    return wrapper


ACTIVATION_PAYLOAD = {
    'fullName': 'Asha Nair',
    'contactNumber': '+919876543210',
    'city': 'Kochi',
    'emailAddress': 'Asha@Example.com',
    'make': 'Maruti',
    'model': 'Swift',
    'registrationNumber': 'kl 07 ab 1234',
    'vehicleType': 'Car',
    'yearOfManufacturing': '2020',
}


def verify_email_in_session(client, qr_id, email, typed=''):
    """What a successful email-OTP verify leaves in the session."""
    import time
    from admin_app import activation_email_otp as email_otp

    session = client.session
    verified = dict(session.get(email_otp.SESSION_KEY) or {})
    verified[qr_id] = {'email': email, 'typed': typed or email, 'at': time.time()}
    session[email_otp.SESSION_KEY] = verified
    session.save()


class _FakeDBMixin:
    def setUp(self):
        self.fake = FakeDB()
        for target, value in (
            ('admin_app.views.db', self.fake),
            ('admin_app.views.firestore.client', lambda: self.fake),
            ('admin_app.views.firestore.transactional', _passthrough_transactional),
        ):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)


@override_settings(ACTIVATION_EMAILS_SYNC=True)
class ActivateIdTests(_FakeDBMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fake.store['qrcodes'] = {'QR1': {'isAssigned': False}}
        self.url = reverse('activate_id', args=['QR1'])
        for target, kwargs in (
            ('admin_app.views.is_activate_phone_verified', {'return_value': True}),
            ('admin_app.views.send_welcome_email_for_id', {}),
            ('admin_app.views.send_vehicle_registration_email', {}),
            ('admin_app.views.auth.get_user_by_email', {'side_effect': fb_auth.UserNotFoundError('none')}),
            ('admin_app.views.auth.delete_user', {}),
            ('admin_app.views.auth.create_user', {'return_value': SimpleNamespace(uid='U9')}),
            (
                'admin_app.views.create_or_update_firebase_user',
                {'return_value': (SimpleNamespace(uid='UID1'), 'Pw!12345abcd', True)},
            ),
        ):
            p = patch(target, **kwargs)
            setattr(self, target.rsplit('.', 1)[-1], p.start())
            self.addCleanup(p.stop)
        p = patch('admin_app.views.auth.update_user')
        self.update_user = p.start()
        self.addCleanup(p.stop)
        verify_email_in_session(self.client, 'QR1', 'asha@example.com', 'Asha@Example.com')

    def _post(self, payload=None, raw=None):
        return self.client.post(
            self.url,
            data=raw if raw is not None else json.dumps(payload or ACTIVATION_PAYLOAD),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_success_assigns_qr_and_normalizes_email_and_plate(self):
        res = self._post()
        self.assertEqual(res.status_code, 200, res.content)
        qr = self.fake.store['qrcodes']['QR1']
        self.assertTrue(qr['isAssigned'])
        self.assertEqual(qr['userID'], 'UID1')
        vehicle = self.fake.store['vehicles'][qr['vehicleID']]
        self.assertEqual(vehicle['registrationNumber'], 'KL07AB1234')
        self.assertEqual(vehicle['qrCodeId'], 'QR1')
        self.assertEqual(self.fake.store['users']['UID1']['emailAddress'], 'asha@example.com')

    def test_confirmation_email_failure_does_not_fail_or_roll_back(self):
        self.send_vehicle_registration_email.side_effect = RuntimeError('smtp down')
        res = self._post()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['status'], 'success')
        self.delete_user.assert_not_called()
        self.assertIn('UID1', self.fake.store['users'])

    def _post_with_photos(self, files, payload=None):
        data = {**(payload or ACTIVATION_PAYLOAD), 'photos': files}
        return self.client.post(
            self.url, data=data, HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def _jpeg(self, name='car.jpg'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b'\xff\xd8\xff fake', content_type='image/jpeg')

    def test_multipart_activation_saves_vehicle_photos(self):
        with patch(
            'admin_app.vehicle_photos.upload_vehicle_photo_bytes',
            side_effect=['https://img/1.jpg', 'https://img/2.jpg'],
        ) as upload:
            res = self._post_with_photos([self._jpeg('a.jpg'), self._jpeg('b.jpg')])
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(upload.call_count, 2)
        qr = self.fake.store['qrcodes']['QR1']
        vehicle = self.fake.store['vehicles'][qr['vehicleID']]
        self.assertEqual(vehicle['photoUrls'], ['https://img/1.jpg', 'https://img/2.jpg'])
        self.assertEqual(vehicle['registrationNumber'], 'KL07AB1234')
        self.assertEqual(upload.call_args.kwargs['vehicle_id'], qr['vehicleID'])

    def test_non_image_photo_is_rejected_before_account_creation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile('x.pdf', b'%PDF', content_type='application/pdf')
        res = self._post_with_photos([bad])
        self.assertEqual(res.status_code, 400)
        self.assertIn('vehiclePhotos', res.json()['errors'])
        self.create_or_update_firebase_user.assert_not_called()
        self.assertFalse(self.fake.store['qrcodes']['QR1']['isAssigned'])

    def test_too_many_photos_are_rejected(self):
        res = self._post_with_photos([self._jpeg(f'{i}.jpg') for i in range(6)])
        self.assertEqual(res.status_code, 400)
        self.assertIn('vehiclePhotos', res.json()['errors'])

    def test_photo_upload_failure_rolls_back_and_cleans_up(self):
        with patch(
            'admin_app.vehicle_photos.upload_vehicle_photo_bytes',
            side_effect=['https://img/1.jpg', RuntimeError('cloudinary down')],
        ), patch('admin_app.vehicle_photos.delete_storage_url') as delete_url:
            res = self._post_with_photos([self._jpeg('a.jpg'), self._jpeg('b.jpg')])
        self.assertEqual(res.status_code, 502)
        self.assertIn('vehiclePhotos', res.json()['errors'])
        delete_url.assert_called_once_with('https://img/1.jpg')
        self.delete_user.assert_called_once_with('UID1')
        self.assertFalse(self.fake.store['qrcodes']['QR1']['isAssigned'])
        self.assertFalse(self.fake.store.get('vehicles'))

    def test_lost_race_returns_409_and_removes_new_account(self):
        # Another activation claims the QR after the page-level check passed.
        real_claim = views._activate_id_claim_qr

        def claim_after_other_winner(qr_ref, *args, **kwargs):
            self.fake.store['qrcodes']['QR1']['isAssigned'] = True
            return real_claim(qr_ref, *args, **kwargs)

        with patch('admin_app.views._activate_id_claim_qr', claim_after_other_winner):
            res = self._post()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()['error_type'], 'already_activated')
        self.delete_user.assert_called_once_with('UID1')
        self.assertNotIn('UID1', self.fake.store.get('users', {}))
        self.assertFalse(self.fake.store.get('vehicles'))

    def test_password_email_sent_only_after_successful_activation(self):
        res = self._post()
        self.assertEqual(res.status_code, 200)
        self.send_welcome_email_for_id.assert_called_once()
        self.assertEqual(
            self.send_welcome_email_for_id.call_args.kwargs['password'],
            res.json()['ui_notice']['account_welcome']['temporary_password'],
        )

    def test_failed_activation_never_emails_a_password(self):
        with patch('admin_app.views._activate_id_claim_qr', side_effect=RuntimeError('boom')):
            res = self._post()
        self.assertEqual(res.status_code, 500)
        self.send_welcome_email_for_id.assert_not_called()
        self.delete_user.assert_called_once_with('UID1')

    def test_profile_without_login_is_restored_with_same_uid(self):
        # Left behind by an earlier failed activation: profile exists, login deleted.
        self.fake.store['users'] = {'U9': {
            'emailAddress': 'asha@example.com',
            'contactNumber': '+919876543210',
            'fullName': 'Asha Nair',
        }}
        res = self._post()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.create_user.call_args.kwargs['uid'], 'U9')
        self.assertTrue(res.json()['ui_notice']['account_welcome']['temporary_password'])
        self.send_welcome_email_for_id.assert_called_once()
        self.assertEqual(self.fake.store['qrcodes']['QR1']['userID'], 'U9')

    def test_profile_without_login_is_restored_by_verified_email_alone(self):
        # Ownership is proven by the email OTP, so a different phone no longer blocks it.
        self.fake.store['users'] = {'U9': {
            'emailAddress': 'asha@example.com',
            'contactNumber': '+919999999999',
            'fullName': 'Asha Nair',
        }}
        res = self._post()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.create_user.call_args.kwargs['uid'], 'U9')
        self.assertEqual(self.fake.store['qrcodes']['QR1']['userID'], 'U9')
        vehicle = self.fake.store['vehicles'][self.fake.store['qrcodes']['QR1']['vehicleID']]
        self.assertEqual(vehicle['ownerContact'], '+919999999999')

    def test_failure_after_restoring_login_keeps_profile(self):
        self.fake.store['users'] = {'U9': {
            'emailAddress': 'asha@example.com',
            'contactNumber': '+919876543210',
        }}
        with patch('admin_app.views._activate_id_claim_qr', side_effect=RuntimeError('boom')):
            res = self._post()
        self.assertEqual(res.status_code, 500)
        self.delete_user.assert_called_once_with('U9')
        self.assertIn('U9', self.fake.store['users'])

    def test_already_activated_qr_redirects_to_notify(self):
        self.fake.store['qrcodes']['QR1']['isAssigned'] = True
        res = self._post()
        self.assertEqual(res.status_code, 302)
        self.assertIn('send-notification-final', res['Location'])

    def test_unverified_phone_is_rejected(self):
        self.is_activate_phone_verified.return_value = False
        res = self._post()
        self.assertEqual(res.status_code, 400)
        self.assertIn('contactNumber', res.json()['errors'])
        self.assertFalse(self.fake.store['qrcodes']['QR1']['isAssigned'])

    def test_malformed_json_returns_json_400(self):
        res = self._post(raw='{not json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['status'], 'error')

    def test_whitespace_only_required_field_is_rejected(self):
        res = self._post({**ACTIVATION_PAYLOAD, 'fullName': '   '})
        self.assertEqual(res.status_code, 400)
        self.assertIn('fullName', res.json()['errors'])

    def test_activation_requires_verified_email(self):
        session = self.client.session
        session.pop('activate_email_verified', None)
        session.save()
        res = self._post()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error_type'], 'email_not_verified')
        self.create_or_update_firebase_user.assert_not_called()
        self.assertFalse(self.fake.store['qrcodes']['QR1']['isAssigned'])

    def test_email_in_payload_cannot_override_verified_email(self):
        res = self._post({**ACTIVATION_PAYLOAD, 'emailAddress': 'victim@example.com'})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(
            self.create_or_update_firebase_user.call_args.kwargs['email'], 'asha@example.com',
        )
        self.assertEqual(self.fake.store['users']['UID1']['emailAddress'], 'asha@example.com')


class AdminAccessTests(_FakeDBMixin, TestCase):
    def _login(self):
        session = self.client.session
        session['admin'] = True
        session.save()

    def test_orders_require_admin(self):
        self.assertEqual(self.client.get(reverse('view_orders')).status_code, 302)
        res = self.client.post(reverse('export_orders_with_qr'), {'order_ids': ['O1']})
        self.assertEqual(res.status_code, 302)

    def test_update_order_status_requires_admin_and_valid_status(self):
        self.fake.store['orders'] = {'O1': {'orderStatus': 0}}
        url = reverse('update_order_status')
        body = json.dumps({'orderId': 'O1', 'newStatus': 3})
        res = self.client.post(url, body, content_type='application/json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(self.fake.store['orders']['O1']['orderStatus'], 0)

        self._login()
        bad = self.client.post(url, json.dumps({'orderId': 'O1', 'newStatus': 99}),
                               content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(url, body, content_type='application/json')
        self.assertTrue(ok.json()['success'])
        self.assertEqual(self.fake.store['orders']['O1']['orderStatus'], 3)

    def test_bulk_delete_skips_admin_accounts(self):
        self._login()
        self.fake.store['users'] = {
            'A1': {'emailAddress': 'other-admin@example.com', 'roleId': 1},
            'U1': {'emailAddress': 'user@example.com', 'roleId': 0},
        }
        self.client.post(reverse('manage_users'), {
            'delete_selected': '1',
            'selected_users': ['A1', 'U1'],
        })
        self.assertIn('A1', self.fake.store['users'])
        self.assertNotIn('U1', self.fake.store['users'])

    def test_unassign_returns_qr_to_pool_and_unlinks_vehicle(self):
        self._login()
        self.fake.store['qrcodes'] = {'QR1': {'isAssigned': True, 'userID': 'U1', 'vehicleID': 'V1'}}
        self.fake.store['vehicles'] = {'V1': {'qrCodeId': 'QR1', 'isQrGenerated': True}}
        url = reverse('unassign_qr_code', args=['QR1'])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        qr = self.fake.store['qrcodes']['QR1']
        self.assertFalse(qr['isAssigned'])
        self.assertNotIn('vehicleID', qr)
        vehicle = self.fake.store['vehicles']['V1']
        self.assertFalse(vehicle['isQrGenerated'])
        self.assertNotIn('qrCodeId', vehicle)

    def test_unassign_requires_admin(self):
        self.fake.store['qrcodes'] = {'QR1': {'isAssigned': True}}
        self.client.post(reverse('unassign_qr_code', args=['QR1']))
        self.assertTrue(self.fake.store['qrcodes']['QR1']['isAssigned'])

    def test_assign_refuses_vehicle_that_already_has_a_qr(self):
        self._login()
        self.fake.store['qrcodes'] = {'QR2': {'isAssigned': False}}
        self.fake.store['users'] = {'U1': {'fullName': 'A'}}
        self.fake.store['vehicles'] = {'V1': {'ownerId': 'U1', 'qrCodeId': 'QR1'}}
        self.client.post(reverse('assign_qr'), {'qr_id': 'QR2', 'user_id': 'U1', 'vehicle_id': 'V1'})
        self.assertFalse(self.fake.store['qrcodes']['QR2']['isAssigned'])
        self.assertEqual(self.fake.store['vehicles']['V1']['qrCodeId'], 'QR1')


class PublicScanAndPlateLookupTests(_FakeDBMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('public_lookup_vehicle')
        self.fake.store['users'] = {'U1': {'fullName': 'Owner'}}
        self.fake.store['qrcodes'] = {
            'QRLIVE01': {'isAssigned': True, 'vehicleID': 'V1', 'userID': 'U1'},
            'QRFREE01': {'isAssigned': False},
            'QRORPHAN': {'isAssigned': True, 'vehicleID': 'GONE', 'userID': 'U1'},
        }
        self.fake.store['vehicles'] = {
            # Stale duplicate of the same plate, pointing at a QR now owned by V1.
            'V0': {'registrationNumber': 'KL13AU6368', 'isQrGenerated': True, 'qrCodeId': 'QRLIVE01'},
            'V1': {'registrationNumber': 'KL13AU6368', 'isQrGenerated': True,
                   'qrCodeId': 'QRLIVE01', 'ownerId': 'U1'},
            # Points at a QR that does not exist.
            'V2': {'registrationNumber': 'KL10AY2728', 'isQrGenerated': True, 'qrCodeId': 'NOPE1234'},
            # Link only on the QR side.
            'V3': {'registrationNumber': 'KL11BE6888'},
        }
        self.fake.store['qrcodes']['QRSIDE01'] = {'isAssigned': True, 'vehicleID': 'V3'}
        self.fake.store['multipurpose_qrs'] = {'SMARTTAG1': {'isAssigned': True}}

    def _lookup(self, **payload):
        return self.client.post(self.url, json.dumps(payload), content_type='application/json')

    def test_plate_with_stale_duplicate_resolves_to_live_vehicle(self):
        res = self._lookup(mode='plate', plate='kl 13 au 6368')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['qr_id'], 'QRLIVE01')

    def test_plate_whose_qr_is_missing_is_not_found(self):
        res = self._lookup(mode='plate', plate='KL10AY2728')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()['error_type'], 'not_found')

    def test_plate_linked_only_from_qr_side_is_found(self):
        res = self._lookup(mode='plate', plate='KL11BE6888')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['qr_id'], 'QRSIDE01')

    def test_scan_of_inactive_qr_opens_activation(self):
        res = self._lookup(mode='qr', qr='https://sudotag.com/admin/send-notification/QRFREE01/')
        self.assertEqual(res.json()['next'], 'activate')

    def test_scan_of_sticker_without_vehicle_says_not_linked(self):
        res = self._lookup(mode='qr', qr='https://sudotag.com/admin/send-notification/QRORPHAN/')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()['error_type'], 'not_linked')

    def test_scan_of_smart_tag_url_opens_smart_tag_page(self):
        res = self._lookup(mode='qr', qr='https://sudotag.com/admin/mp/SMARTTAG1/')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['next'], 'smart_tag')
        self.assertIn('/admin/mp/SMARTTAG1/', res.json()['redirect_url'])

    def test_bare_smart_tag_id_is_recognised(self):
        res = self._lookup(mode='qr', qr='SMARTTAG1')
        self.assertEqual(res.json()['next'], 'smart_tag')

    def test_notify_page_for_sticker_without_vehicle_is_friendly(self):
        res = self.client.get(reverse('send_notification', args=['QRORPHAN']))
        self.assertEqual(res.status_code, 404)
        self.assertContains(res, 'linked to a vehicle', status_code=404)

    def test_notify_url_with_smart_tag_id_redirects(self):
        res = self.client.get(reverse('send_notification', args=['SMARTTAG1']))
        self.assertRedirects(res, reverse('multipurpose_qr_scan', args=['SMARTTAG1']),
                             fetch_redirect_response=False)
