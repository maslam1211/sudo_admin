from unittest import mock

from django.test import TestCase
from firebase_admin import firestore

from admin_app import customer_admin as ca
from admin_app.models import ArchivedUser, ArchivedVehicle


# ─── In-memory Firestore ────────────────────────────────────────────────────

class Snap:
    def __init__(self, ref, data):
        self.reference, self.id, self._data = ref, ref.id, data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Doc:
    def __init__(self, store, path):
        self.store, self.path, self.id = store, path, path.split('/')[-1]

    def get(self):
        return Snap(self, self.store.get(self.path))

    def _apply(self, base, data):
        for k, v in data.items():
            if v is firestore.DELETE_FIELD:
                base.pop(k, None)
            elif v is firestore.SERVER_TIMESTAMP:
                base[k] = 'TS'
            else:
                base[k] = v
        return base

    def update(self, data):
        if self.path not in self.store:
            raise KeyError(self.path)
        self.store[self.path] = self._apply(dict(self.store[self.path]), data)

    def set(self, data, merge=False):
        base = dict(self.store.get(self.path, {})) if merge else {}
        self.store[self.path] = self._apply(base, data)

    def delete(self):
        self.store.pop(self.path, None)


class Col:
    def __init__(self, store, name, filters=()):
        self.store, self.name, self.filters = store, name, list(filters)

    def document(self, doc_id):
        return Doc(self.store, f'{self.name}/{doc_id}')

    def where(self, filter=None):
        return Col(self.store, self.name, self.filters + [(filter.field_path, filter.value)])

    def stream(self):
        for path, data in list(self.store.items()):
            if path.rsplit('/', 1)[0] != self.name:
                continue
            if all(data.get(f) == v for f, v in self.filters):
                yield Snap(Doc(self.store, path), data)


class DB:
    def __init__(self, store):
        self.store = store

    def collection(self, name):
        return Col(self.store, name)


class UserNotFoundError(Exception):
    pass


class EmailAlreadyExistsError(Exception):
    pass


class FakeAuth:
    def __init__(self, users=('u1', 'u2')):
        self.users = set(users)
        self.updates, self.deleted = [], []

    def update_user(self, uid, **kw):
        if uid not in self.users:
            raise UserNotFoundError(uid)
        if kw.get('email') == 'taken@x.com':
            raise EmailAlreadyExistsError()
        self.updates.append((uid, kw))

    def delete_user(self, uid):
        if uid not in self.users:
            raise UserNotFoundError(uid)
        self.users.discard(uid)
        self.deleted.append(uid)


def world():
    return {
        'users/u1': {'fullName': 'Arjun P', 'emailAddress': 'arjun@x.com', 'contactNumber': '9876543210',
                     'city': 'Kochi', 'vehicleCount': 2},
        'users/u2': {'fullName': 'Sara K', 'emailAddress': 'sara@x.com', 'contactNumber': '9123456780', 'vehicleCount': 0},
        'vehicles/v1': {'ownerId': 'u1', 'registrationNumber': 'KL10AB1234', 'make': 'Maruti', 'model': 'Swift',
                        'vehicleType': 'Car', 'qrCodeId': 'Q1', 'ownerFullName': 'Arjun P', 'ownerContact': '9876543210',
                        'assignedFamilyMemberId': 'f1'},
        'vehicles/v2': {'ownerId': 'u1', 'registrationNumber': 'KL07CD5678', 'make': 'Honda', 'vehicleType': 'Bike'},
        'qrcodes/Q1': {'isAssigned': True, 'userID': 'u1', 'vehicleID': 'v1', 'assignedAt': 'T'},
        'qrcodes/Q2': {'isAssigned': True, 'userID': 'u1', 'vehicleID': 'gone'},
        'multipurpose_qrs/T1': {'isAssigned': True, 'userID': 'u1', 'ownerFullName': 'Arjun P', 'contactNumber': '9876543210',
                                'purpose': 'multipurpose', 'title': 'Pet tag'},
        'orders/o1': {'userId': 'u1', 'amount': 799},
    }


class CustomerEditTests(TestCase):
    def setUp(self):
        self.store = world()
        self.db = DB(self.store)
        self.auth = FakeAuth()

    def form(self, **kw):
        f = {'fullName': 'Arjun Pandath', 'emailAddress': 'arjun@x.com', 'contactNumber': '9876543210',
             'city': 'Kozhikode', 'bloodGroup': 'b+', 'defaultEmergencyContact': ''}
        f.update(kw)
        return f

    def test_name_change_reaches_vehicles_and_smart_tags(self):
        res = ca.update_customer(self.db, 'u1', self.form(), auth_module=self.auth)
        self.assertEqual(sorted(res['changed']), ['bloodGroup', 'city', 'fullName'])
        self.assertEqual(self.store['users/u1']['bloodGroup'], 'B+')
        self.assertEqual(self.store['vehicles/v1']['ownerFullName'], 'Arjun Pandath')
        self.assertEqual(self.store['vehicles/v2']['ownerFullName'], 'Arjun Pandath')
        self.assertEqual(self.store['multipurpose_qrs/T1']['ownerFullName'], 'Arjun Pandath')
        self.assertEqual(self.auth.updates, [])  # email/phone unchanged → sign-in untouched

    def test_email_and_phone_change_update_sign_in(self):
        ca.update_customer(self.db, 'u1', self.form(emailAddress='new@x.com', contactNumber='+91 98765 00000'),
                           auth_module=self.auth)
        self.assertEqual(self.auth.updates, [('u1', {'email': 'new@x.com', 'phone_number': '+919876500000'})])
        self.assertEqual(self.store['vehicles/v1']['ownerContact'], '9876500000')

    def test_refusals_change_nothing(self):
        before = dict(self.store['users/u1'])
        for kw, msg in ((dict(emailAddress='sara@x.com'), 'already uses this email'),
                        (dict(contactNumber='9123456780'), 'already uses this mobile'),
                        (dict(contactNumber='12345'), 'valid 10-digit'),
                        (dict(fullName='A'), 'between 2 and 80'),
                        (dict(bloodGroup='Z+'), 'blood group'),
                        (dict(defaultEmergencyContact='9876543210'), "own number"),
                        (dict(emailAddress='taken@x.com'), 'already used by another sign-in')):
            with self.assertRaisesMessage(ca.CustomerAdminError, msg):
                ca.update_customer(self.db, 'u1', self.form(**kw), auth_module=self.auth)
        self.assertEqual(self.store['users/u1'], before)


class VehicleTests(TestCase):
    def setUp(self):
        self.store = world()
        self.db = DB(self.store)

    def test_edit_checks_unique_registration(self):
        with self.assertRaisesMessage(ca.CustomerAdminError, 'already registered'):
            ca.update_vehicle(self.db, 'v1', {'registrationNumber': 'kl 07 cd 5678', 'vehicleType': 'car', 'make': 'Maruti'})
        changed = ca.update_vehicle(self.db, 'v1', {'registrationNumber': 'kl-10-ab-9999', 'vehicleType': 'car',
                                                   'make': 'Maruti', 'model': 'Swift Dzire', 'yearOfManufacturing': '2020'})
        self.assertEqual(sorted(changed), ['model', 'registrationNumber', 'yearOfManufacturing'])
        self.assertEqual(self.store['vehicles/v1']['registrationNumber'], 'KL10AB9999')

    def test_transfer_moves_qr_and_recounts(self):
        res = ca.transfer_vehicle(self.db, 'v1', 'u2')
        v = self.store['vehicles/v1']
        self.assertEqual((v['ownerId'], v['ownerFullName'], v['ownerContact']), ('u2', 'Sara K', '9123456780'))
        self.assertIsNone(v['assignedFamilyMemberId'])
        self.assertEqual(self.store['qrcodes/Q1']['userID'], 'u2')
        self.assertEqual(self.store['users/u2']['vehicleCount'], 1)
        self.assertEqual(self.store['users/u1']['vehicleCount'], 1)
        self.assertEqual(res['to_name'], 'Sara K')

    def test_unlink_qr(self):
        self.assertEqual(ca.unlink_vehicle_qr(self.db, 'v1'), 'Q1')
        self.assertFalse(self.store['qrcodes/Q1']['isAssigned'])
        self.assertNotIn('userID', self.store['qrcodes/Q1'])
        self.assertNotIn('qrCodeId', self.store['vehicles/v1'])
        with self.assertRaisesMessage(ca.CustomerAdminError, 'no QR'):
            ca.unlink_vehicle_qr(self.db, 'v2')

    def test_delete_archives_frees_qr_and_recounts(self):
        res = ca.delete_vehicle(self.db, 'v1')
        self.assertNotIn('vehicles/v1', self.store)
        self.assertFalse(self.store['qrcodes/Q1']['isAssigned'])
        self.assertEqual(self.store['users/u1']['vehicleCount'], 1)
        self.assertTrue(res['qr_freed'])
        self.assertEqual(ArchivedVehicle.objects.get(vehicle_id='v1').registration_number, 'KL10AB1234')

    def test_find_customer_by_email_or_phone(self):
        self.assertEqual([d.id for d in ca.find_customer(self.db, 'SARA@x.com'.lower())], ['u2'])
        self.assertEqual([d.id for d in ca.find_customer(self.db, '+91 91234 56780')], ['u2'])
        self.assertEqual(ca.find_customer(self.db, 'nobody'), [])


class CustomerDeleteTests(TestCase):
    def test_full_delete(self):
        store = world()
        db = DB(store)
        auth = FakeAuth()
        res = ca.delete_customer(db, 'u1', auth_module=auth, is_protected=lambda d: False)
        self.assertEqual(res, {'vehicles': 2, 'qrs_freed': 2, 'smart_tags_freed': 1, 'auth_deleted': True})
        self.assertNotIn('users/u1', store)
        self.assertNotIn('vehicles/v1', store)
        self.assertNotIn('vehicles/v2', store)
        self.assertFalse(store['qrcodes/Q1']['isAssigned'])
        self.assertFalse(store['qrcodes/Q2']['isAssigned'])
        tag = store['multipurpose_qrs/T1']
        self.assertEqual(tag, {'isAssigned': False, 'purpose': 'multipurpose', 'updatedAt': 'TS'})
        self.assertIn('orders/o1', store)  # orders kept
        self.assertEqual(auth.deleted, ['u1'])
        self.assertEqual(ArchivedUser.objects.get(user_id='u1').full_name, 'Arjun P')
        self.assertEqual(ArchivedVehicle.objects.filter(owner_id='u1').count(), 2)

    def test_protected_admin_is_not_deleted(self):
        store = world()
        with self.assertRaisesMessage(ca.CustomerAdminError, 'Admin accounts'):
            ca.delete_customer(DB(store), 'u1', auth_module=FakeAuth(), is_protected=lambda d: True)
        self.assertIn('users/u1', store)

    def test_profile_without_sign_in_account(self):
        store = world()
        res = ca.delete_customer(DB(store), 'u1', auth_module=FakeAuth(users=()), is_protected=lambda d: False)
        self.assertFalse(res['auth_deleted'])
        self.assertNotIn('users/u1', store)


class PageTests(TestCase):
    def setUp(self):
        self.store = world()
        self.db = DB(self.store)
        s = self.client.session
        s['admin'] = True
        s.save()
        for p in (mock.patch('admin_app.customer_admin_views._db', return_value=self.db),
                  mock.patch('admin_app.customer_admin_views._auth', return_value=FakeAuth()),
                  mock.patch('admin_app.context_processors.civic_sense_badge', return_value={})):
            p.start()
            self.addCleanup(p.stop)

    def test_customer_page_and_delete_needs_confirmation(self):
        r = self.client.get('/admin/customers/u1/')
        self.assertContains(r, 'KL10AB1234')
        self.assertContains(r, 'Delete customer')
        r = self.client.post('/admin/customers/u1/', {'action': 'delete', 'confirm': 'wrong'}, follow=True)
        self.assertContains(r, 'to confirm')
        self.assertIn('users/u1', self.store)
        r = self.client.post('/admin/customers/u1/', {'action': 'delete', 'confirm': 'ARJUN@x.com'})
        self.assertRedirects(r, '/admin/manage-users/', fetch_redirect_response=False)
        self.assertNotIn('users/u1', self.store)

    def test_vehicle_delete_needs_registration(self):
        r = self.client.post('/admin/manage-vehicles/v1/action/', {'action': 'delete', 'confirm': 'nope'})
        self.assertIn('vehicles/v1', self.store)
        r = self.client.post('/admin/manage-vehicles/v1/action/', {'action': 'delete', 'confirm': 'kl10 ab1234'})
        self.assertRedirects(r, '/admin/customers/u1/', fetch_redirect_response=False)
        self.assertNotIn('vehicles/v1', self.store)

    def test_needs_admin(self):
        self.client.session.flush()
        self.client.cookies.pop('sessionid', None)
        self.assertEqual(self.client.get('/admin/customers/u1/').status_code, 302)
        self.assertEqual(self.client.post('/admin/manage-vehicles/v1/action/', {'action': 'delete'}).status_code, 302)
        self.assertIn('vehicles/v1', self.store)


class DuplicateVehicleTests(TestCase):
    def test_deleting_one_duplicate_keeps_the_sticker_with_the_other(self):
        store = world()
        store['vehicles/v3'] = dict(store['vehicles/v1'])  # same registration, same QR
        db = DB(store)
        self.assertEqual(ca.duplicate_registrations([store['vehicles/v1'], store['vehicles/v3'], store['vehicles/v2']]),
                         ['KL10AB1234'])
        res = ca.delete_vehicle(db, 'v1')
        self.assertFalse(res['qr_freed'])
        self.assertTrue(store['qrcodes/Q1']['isAssigned'])
        self.assertEqual(store['qrcodes/Q1']['vehicleID'], 'v3')
        # Deleting the last copy frees it.
        self.assertTrue(ca.delete_vehicle(db, 'v3')['qr_freed'])
        self.assertFalse(store['qrcodes/Q1']['isAssigned'])
