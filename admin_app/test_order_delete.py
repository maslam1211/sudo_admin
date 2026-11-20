import json
from unittest import mock

from django.test import SimpleTestCase

from admin_app import order_delete_views
from admin_app.test_civic_sense import FakeDB


class FakeBatch:
    def __init__(self, store):
        self.store, self.ops = store, []

    def set(self, ref, data):
        self.ops.append(('set', ref, data))

    def delete(self, ref):
        self.ops.append(('delete', ref, None))

    def commit(self):
        for op, ref, data in self.ops:
            if op == 'set':
                self.store[ref.path] = dict(data)
            else:
                self.store.pop(ref.path, None)
        self.ops = []


class BatchDB(FakeDB):
    def batch(self):
        return FakeBatch(self.store)


def db_with_orders():
    return BatchDB({
        'orders/o1': {'fullName': 'Aslam', 'amount': 799.0, 'paymentStatus': 'pending'},
        'orders/o2': {'fullName': 'Salman', 'amount': 1.0, 'paymentStatus': 'paid'},
    })


class DeleteOrdersTests(SimpleTestCase):
    def test_archives_then_deletes(self):
        db = db_with_orders()
        deleted, missing = order_delete_views.delete_orders(db, ['o1', 'nope'], 'a@sudotag.com')
        self.assertEqual((deleted, missing), (['o1'], ['nope']))
        self.assertNotIn('orders/o1', db.store)
        self.assertIn('orders/o2', db.store)
        copy = db.store['deleted_orders/o1']
        self.assertEqual(copy['fullName'], 'Aslam')
        self.assertEqual(copy['deletedBy'], 'a@sudotag.com')
        self.assertEqual(copy['originalId'], 'o1')


class DeleteOrdersViewTests(SimpleTestCase):
    databases = {'default'}

    def post(self, body, admin=True):
        if admin:
            s = self.client.session
            s['admin'] = True
            s['email'] = 'a@sudotag.com'
            s.save()
        return self.client.post('/admin/orders/delete/', json.dumps(body), content_type='application/json')

    def test_requires_admin(self):
        self.assertEqual(self.post({'orderIds': ['o1']}, admin=False).status_code, 403)

    def test_deletes_selected(self):
        db = db_with_orders()
        with mock.patch.object(order_delete_views, '_get_db', return_value=db):
            r = self.post({'orderIds': ['o1', 'o2', 'o1']})
        self.assertEqual(r.json()['deleted'], ['o1', 'o2'])
        self.assertFalse([k for k in db.store if k.startswith('orders/')])

    def test_rejects_empty_and_bad_ids(self):
        self.assertEqual(self.post({'orderIds': []}).status_code, 400)
        self.assertEqual(self.post({'orderIds': ['../users/x']}).status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get('/admin/orders/delete/').status_code, 405)
