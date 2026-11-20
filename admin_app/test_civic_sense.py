from datetime import datetime, timezone
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from admin_app import civic_sense


class FakeSnap:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data or {})


class FakeDoc:
    def __init__(self, store, path):
        self.store = store
        self.path = path
        self.id = path.split('/')[-1]

    def get(self):
        return FakeSnap(self, self.store.get(self.path))

    def update(self, data):
        self.store[self.path].update(data)

    def collection(self, name):
        return FakeCollection(self.store, f'{self.path}/{name}')


class FakeCollection:
    def __init__(self, store, path, filters=None):
        self.store = store
        self.path = path
        self.filters = filters or []

    def document(self, doc_id):
        return FakeDoc(self.store, f'{self.path}/{doc_id}')

    def _docs(self):
        prefix = self.path + '/'
        for path, data in self.store.items():
            rest = path[len(prefix):]
            if path.startswith(prefix) and '/' not in rest:
                yield FakeDoc(self.store, path), data

    def where(self, filter=None):
        return FakeCollection(self.store, self.path, self.filters + [filter])

    def order_by(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def stream(self):
        for ref, data in list(self._docs()):
            ok = True
            for f in self.filters:
                value = data.get(f.field_path)
                if f.op_string == '==' and value != f.value:
                    ok = False
                if f.op_string == '>' and not (value or 0) > f.value:
                    ok = False
            if ok:
                yield FakeSnap(ref, data)


class FakeDB:
    def __init__(self, store):
        self.store = store

    def collection(self, name):
        return FakeCollection(self.store, name)


def ts(day):
    return datetime(2026, 11, day, tzinfo=timezone.utc)


def make_db():
    return FakeDB({
        'community_posts/p1': {'title': 'Pothole on MG Road', 'description': 'Huge pothole', 'authorName': 'Asha',
                               'authorId': 'u1', 'reportsCount': 2, 'moderationStatus': 'approved', 'status': 'active',
                               'category': 'Roads', 'createdAt': ts(10)},
        'community_posts/p1/reports/r1': {'reporterId': 'u2', 'reason': 'Spam', 'createdAt': ts(11)},
        'community_posts/p1/reports/r2': {'reporterId': 'u3', 'reason': 'Abusive', 'details': 'Rude words', 'createdAt': ts(12)},
        'community_posts/p2': {'title': 'Garbage dump', 'status': 'removed', 'moderationStatus': 'rejected',
                               'isDeleted': True, 'createdAt': ts(9)},
        'community_posts/p3': {'title': 'Broken signal', 'moderationStatus': 'pending', 'createdAt': ts(8)},
        'community_posts/p4': {'title': 'Clean park', 'moderationStatus': 'approved', 'status': 'active', 'createdAt': ts(7)},
        'users/u2': {'fullName': 'Ravi', 'emailAddress': 'ravi@example.com', 'contactNumber': '9000000000'},
    })


class PostStateTests(SimpleTestCase):
    def test_states(self):
        self.assertEqual(civic_sense.post_state({'reportsCount': 3}), 'reported')
        self.assertEqual(civic_sense.post_state({'reportsCount': 3, 'isDeleted': True}), 'removed')
        self.assertEqual(civic_sense.post_state({'moderationStatus': 'rejected'}), 'removed')
        self.assertEqual(civic_sense.post_state({}), 'pending')
        self.assertEqual(civic_sense.post_state({'moderationStatus': 'approved'}), 'live')

    def test_images_merge_single_and_list(self):
        post = civic_sense.normalize_post('x', {'imageUrl': 'https://a/1.jpg', 'imageUrls': ['https://a/2.jpg', 'bad']})
        self.assertEqual(post['images'], ['https://a/1.jpg', 'https://a/2.jpg'])


class ListPostsTests(SimpleTestCase):
    def test_counts_and_filter(self):
        result = civic_sense.list_posts(make_db(), state='reported')
        self.assertEqual([p['id'] for p in result['posts']], ['p1'])
        self.assertEqual(result['counts'], {'reported': 1, 'pending': 1, 'live': 1, 'removed': 1, 'all': 4})

    def test_search(self):
        result = civic_sense.list_posts(make_db(), state='all', query='signal')
        self.assertEqual([p['id'] for p in result['posts']], ['p3'])


class ReportsAndModerationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_reports_newest_first_with_reporter(self):
        db = make_db()
        reports = civic_sense.get_reports(db, 'p1')
        self.assertEqual([r['reason'] for r in reports], ['Abusive', 'Spam'])
        users = civic_sense.get_users(db, [r['reporter_id'] for r in reports])
        self.assertEqual(users['u2']['phone'], '9000000000')

    def test_remove_writes_app_fields_and_resolves_reports(self):
        db = make_db()
        civic_sense.moderate(db, 'p1', 'remove', 'admin@sudotag.com', 'Spam')
        post = db.store['community_posts/p1']
        self.assertEqual(post['status'], 'removed')
        self.assertEqual(post['moderationStatus'], 'rejected')
        self.assertTrue(post['isDeleted'])
        self.assertEqual(post['moderatedBy'], 'admin@sudotag.com')
        self.assertEqual(post['moderationNote'], 'Spam')
        self.assertEqual(db.store['community_posts/p1/reports/r1']['status'], 'removed')

    def test_dismiss_resets_count_and_keeps_live(self):
        db = make_db()
        civic_sense.moderate(db, 'p1', 'dismiss', 'admin@sudotag.com')
        post = db.store['community_posts/p1']
        self.assertEqual(post['reportsCount'], 0)
        self.assertFalse(post['isDeleted'])
        self.assertNotIn('moderationNote', post)
        self.assertEqual(civic_sense.post_state(post), 'live')

    def test_bad_action_and_missing_post(self):
        with self.assertRaises(ValueError):
            civic_sense.moderate(make_db(), 'p1', 'nuke', 'a')
        with self.assertRaises(ValueError):
            civic_sense.moderate(make_db(), 'nope', 'remove', 'a')

    def test_open_report_count_is_cached(self):
        db = make_db()
        self.assertEqual(civic_sense.open_report_count(db), 1)
        db.store['community_posts/p4']['reportsCount'] = 1
        self.assertEqual(civic_sense.open_report_count(db), 1)


class ViewTests(SimpleTestCase):
    databases = {"default"}

    def test_requires_admin(self):
        response = self.client.get('/admin/civic-sense/')
        self.assertEqual(response.status_code, 302)

    def test_remove_needs_note(self):
        session = self.client.session
        session['admin'] = True
        session.save()
        with mock.patch('admin_app.civic_sense_views._get_db', return_value=make_db()):
            response = self.client.post('/admin/civic-sense/p1/moderate/', {'action': 'remove', 'note': ' '})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/civic-sense/p1/', response['Location'])
