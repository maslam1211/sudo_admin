"""Phase 1: Firebase mirror, worker jobs, outbox, health, DATABASE_URL."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone as dj_tz

from api import mirror, worker
from api.models import (
    FirebaseAuthUser, FirebaseStorageObject, FirestoreDocument, MirrorRun, OutboxEvent,
    RateLimitBucket, ScheduledJob,
)

TS = datetime(2026, 11, 1, 10, 30, tzinfo=timezone.utc)


# ─── fake Firestore with real nesting ────────────────────────────────────────
class FRef:
    def __init__(self, store, path):
        self.store, self.path = store, path
        self.id = path.rsplit('/', 1)[-1]
        self.parent = SimpleNamespace(id=path.rsplit('/', 2)[-2] if '/' in path else '')

    def collections(self):
        prefix = self.path + '/'
        names = sorted({p[len(prefix):].split('/')[0] for p in self.store.all_paths()
                        if p.startswith(prefix) and p[len(prefix):].count('/') >= 1})
        return [FCol(self.store, f'{self.path}/{n}') for n in names]


class FSnap:
    def __init__(self, ref, data):
        self.reference, self.id, self._data = ref, ref.id, data
        self.create_time = TS
        self.update_time = TS

    def to_dict(self):
        return dict(self._data)


class FCol:
    def __init__(self, store, path):
        self.store, self.path = store, path
        self.id = path.rsplit('/', 1)[-1]

    def _children(self):
        prefix = self.path + '/'
        return sorted({p[len(prefix):].split('/')[0] for p in self.store.all_paths() if p.startswith(prefix)})

    def stream(self):
        if self.store.fail_on == self.path:
            raise RuntimeError('network down')
        return [FSnap(FRef(self.store, f'{self.path}/{d}'), self.store.docs[f'{self.path}/{d}'])
                for d in self._children() if f'{self.path}/{d}' in self.store.docs]

    def list_documents(self, page_size=None):
        return [FRef(self.store, f'{self.path}/{d}') for d in self._children()]


class FStore:
    def __init__(self, docs):
        self.docs = docs
        self.fail_on = None

    def all_paths(self):
        return list(self.docs)

    def collections(self):
        return [FCol(self, n) for n in sorted({p.split('/')[0] for p in self.docs})]


def seed():
    geo = SimpleNamespace(latitude=9.93, longitude=76.26)
    ref = SimpleNamespace(path='users/u1', id='u1', parent=None)
    return FStore({
        'users/u1': {'fullName': 'A', 'createdAt': TS, 'tags': ['x', 1], 'loc': geo, 'me': ref},
        'users/u1/user-settings/u1': {'enableSms': False},
        'vehicles/v1': {'ownerId': 'u1', 'photoUrls': [], 'raw': b'\x00\x01'},
        # chats/c1 has no fields of its own, only a messages subcollection
        'chats/c1/messages/m1': {'text': 'hi', 'timestamp': TS},
    })


class MirrorFirestoreTests(TestCase):
    def test_copies_every_document_and_subcollection_with_types(self):
        stats = mirror.mirror_firestore(seed())
        paths = set(FirestoreDocument.objects.values_list('path', flat=True))
        self.assertEqual(paths, {'users/u1', 'users/u1/user-settings/u1', 'vehicles/v1',
                                 'chats/c1', 'chats/c1/messages/m1'})
        self.assertEqual(stats['missing_parents'], 1)
        user = FirestoreDocument.objects.get(path='users/u1')
        self.assertEqual(user.data['createdAt'], {'__type': 'timestamp', 'value': TS.isoformat()})
        self.assertEqual(user.data['loc'], {'__type': 'geopoint', 'latitude': 9.93, 'longitude': 76.26})
        self.assertEqual(user.data['me'], {'__type': 'ref', 'path': 'users/u1'})
        self.assertEqual(user.collection_id, 'users')
        settings_doc = FirestoreDocument.objects.get(path='users/u1/user-settings/u1')
        self.assertEqual(settings_doc.collection_path, 'users/u1/user-settings')
        self.assertEqual(settings_doc.parent_path, 'users/u1')
        self.assertIsNone(FirestoreDocument.objects.get(path='chats/c1').data)
        self.assertEqual(mirror.decode(FirestoreDocument.objects.get(path='vehicles/v1').data)['raw'], b'\x00\x01')
        self.assertEqual(mirror.decode(user.data)['createdAt'], TS)

    def test_rerun_counts_changes_and_marks_deleted_without_losing_data(self):
        store = seed()
        mirror.mirror_firestore(store)
        store.docs['vehicles/v1'] = {'ownerId': 'u2'}
        del store.docs['users/u1/user-settings/u1']
        stats = mirror.mirror_firestore(store)
        self.assertEqual(stats['changed'], 1)
        self.assertEqual(stats['marked_deleted'], 1)
        gone = FirestoreDocument.objects.get(path='users/u1/user-settings/u1')
        self.assertIsNotNone(gone.deleted_at)
        self.assertEqual(gone.data, {'enableSms': False})  # last copy kept
        store.docs['users/u1/user-settings/u1'] = {'enableSms': True}
        mirror.mirror_firestore(store)
        self.assertIsNone(FirestoreDocument.objects.get(path='users/u1/user-settings/u1').deleted_at)

    def test_failure_halfway_never_marks_documents_deleted(self):
        store = seed()
        mirror.mirror_firestore(store)
        store.fail_on = 'vehicles'
        stats = mirror.mirror_firestore(store)
        self.assertEqual(stats['errors'], 1)
        self.assertEqual(FirestoreDocument.objects.filter(deleted_at__isnull=False).count(), 0)

    def test_only_scopes_deletion_marking(self):
        store = seed()
        mirror.mirror_firestore(store)
        mirror.mirror_firestore(store, collections=['vehicles'])
        self.assertEqual(FirestoreDocument.objects.filter(deleted_at__isnull=False).count(), 0)


class MirrorAuthAndStorageTests(TestCase):
    def test_auth_users_without_password_hashes(self):
        user = SimpleNamespace(
            uid='u1', email='a@b.in', phone_number='+919876543210', display_name='A', photo_url=None,
            email_verified=True, disabled=False, custom_claims=None,
            provider_data=[SimpleNamespace(provider_id='phone', uid='+919876543210', email=None,
                                           phone_number='+919876543210')],
            user_metadata=SimpleNamespace(creation_timestamp=1_700_000_000_000, last_sign_in_timestamp=None),
            password_hash='SECRET',
        )
        page = SimpleNamespace(users=[user], get_next_page=lambda: None)
        auth = SimpleNamespace(list_users=lambda: page)
        FirebaseAuthUser.objects.create(uid='old', synced_at=dj_tz.now())
        stats = mirror.mirror_auth(auth)
        self.assertEqual(stats, {'users': 1, 'marked_deleted': 1})
        row = FirebaseAuthUser.objects.get(uid='u1')
        self.assertEqual(row.providers[0]['providerId'], 'phone')
        self.assertNotIn('SECRET', str(row.__dict__))
        self.assertIsNotNone(FirebaseAuthUser.objects.get(uid='old').deleted_at)

    def test_storage_files_downloaded_once_and_kept_after_source_deletion(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        downloads = []

        def blob(name, md5):
            def download_to_filename(path):
                downloads.append(name)
                Path(path).write_bytes(b'img')
            return SimpleNamespace(name=name, md5_hash=md5, size=3, content_type='image/jpeg',
                                   updated=TS, download_to_filename=download_to_filename)

        blobs = [blob('civic_evidence/u1/r1/a.jpg', 'h1'), blob('community_media/u1/b.jpg', 'h2'),
                 blob('folder/', ''), blob('../escape.jpg', 'h3')]
        bucket = SimpleNamespace(name='b', list_blobs=lambda: blobs)
        mirror.mirror_storage(bucket, root)
        mirror.mirror_storage(bucket, root)
        self.assertEqual(downloads, ['civic_evidence/u1/r1/a.jpg', 'community_media/u1/b.jpg'])
        self.assertTrue((root / 'firebase_storage/civic_evidence/u1/r1/a.jpg').exists())
        self.assertFalse((root.parent / 'escape.jpg').exists())
        blobs.pop(0)
        mirror.mirror_storage(bucket, root)
        kept = FirebaseStorageObject.objects.get(path='civic_evidence/u1/r1/a.jpg')
        self.assertIsNotNone(kept.deleted_at)
        self.assertTrue((root / kept.local_path).exists())

    def test_full_run_records_partial_status(self):
        auth = SimpleNamespace(list_users=mock.Mock(side_effect=RuntimeError('auth down')))
        run = mirror.run_full_mirror(db=seed(), auth=auth)
        self.assertEqual(run.status, 'partial')
        self.assertIn('auth', run.error)
        self.assertEqual(run.stats['firestore']['documents'], 5)
        self.assertEqual(MirrorRun.objects.count(), 1)


# ─── worker ──────────────────────────────────────────────────────────────────
class WorkerJobTests(TestCase):
    def test_job_runs_once_per_interval_and_records_state(self):
        calls = []
        job = worker.Job('t', timedelta(hours=1), lambda: calls.append(1))
        now = dj_tz.now()
        self.assertTrue(worker.run_job(job, now))
        self.assertFalse(worker.run_job(job, now + timedelta(minutes=5)))
        self.assertTrue(worker.run_job(job, now + timedelta(hours=1, seconds=1)))
        row = ScheduledJob.objects.get(name='t')
        self.assertEqual((len(calls), row.run_count, row.last_status), (2, 2, 'ok'))
        self.assertIsNone(row.lease_until)

    def test_leased_job_is_not_run_twice(self):
        job = worker.Job('t', timedelta(minutes=1), lambda: None)
        now = dj_tz.now()
        ScheduledJob.objects.create(name='t', next_run_at=now, lease_until=now + timedelta(minutes=10))
        self.assertFalse(worker.run_job(job, now))

    def test_failure_is_recorded_and_rescheduled(self):
        job = worker.Job('t', timedelta(minutes=1), mock.Mock(side_effect=ValueError('boom')))
        worker.run_job(job)
        row = ScheduledJob.objects.get(name='t')
        self.assertEqual(row.last_status, 'failed')
        self.assertIn('boom', row.last_error)
        self.assertIsNone(row.lease_until)

    def test_disabled_job_never_runs(self):
        job = worker.Job('t', timedelta(minutes=1), mock.Mock(), enabled=lambda: False)
        self.assertFalse(worker.run_job(job))
        job.run.assert_not_called()

    def test_scheduled_push_only_when_web_thread_is_off(self):
        job = next(j for j in worker.JOBS if j.name == 'scheduled_push')
        with self.settings(SCHEDULED_PUSH_IN_WEB=True):
            self.assertFalse(job.enabled())
        with self.settings(SCHEDULED_PUSH_IN_WEB=False):
            self.assertTrue(job.enabled())

    def test_prune_removes_old_rate_limits_and_done_events(self):
        old = dj_tz.now() - timedelta(days=40)
        RateLimitBucket.objects.create(key='k', window_start=old, count=1)
        OutboxEvent.objects.create(topic='x', status='done', available_at=old, processed_at=old)
        OutboxEvent.objects.create(topic='x', status='pending', available_at=old)
        worker._prune()
        self.assertEqual(RateLimitBucket.objects.count(), 0)
        self.assertEqual(list(OutboxEvent.objects.values_list('status', flat=True)), ['pending'])


class OutboxTests(TestCase):
    def setUp(self):
        self.addCleanup(worker.HANDLERS.clear)

    def test_success(self):
        seen = []
        worker.handler('ok.topic')(seen.append)
        worker.enqueue('ok.topic', {'a': 1})
        self.assertEqual(worker.process_outbox(), {'done': 1, 'retry': 0, 'dead': 0})
        self.assertEqual(seen, [{'a': 1}])
        self.assertEqual(OutboxEvent.objects.get().status, 'done')

    def test_retry_with_backoff_then_dead(self):
        worker.handler('bad')(mock.Mock(side_effect=RuntimeError('nope')))
        worker.enqueue('bad')
        now = dj_tz.now()
        for i in range(worker.MAX_ATTEMPTS):
            worker.process_outbox(now=now + timedelta(days=i + 1))
        event = OutboxEvent.objects.get()
        self.assertEqual((event.status, event.attempts), ('dead', worker.MAX_ATTEMPTS))
        self.assertIn('nope', event.last_error)

    def test_delayed_events_wait(self):
        worker.handler('later')(mock.Mock())
        worker.enqueue('later', delay=timedelta(hours=1))
        self.assertEqual(worker.process_outbox()['done'], 0)

    def test_unknown_topic_is_dead_immediately(self):
        worker.enqueue('nobody.listens')
        self.assertEqual(worker.process_outbox()['dead'], 1)


class HealthAndSettingsTests(TestCase):
    def test_health_reports_db_and_worker(self):
        body = Client().get('/api/v1/health').json()
        self.assertEqual(body['ok'], True)
        self.assertEqual(body['worker'], {'state': 'not-started'})
        worker.run_job(next(j for j in worker.JOBS if j.name == 'heartbeat'))
        self.assertEqual(Client().get('/api/v1/health').json()['worker']['state'], 'ok')

    def test_request_id_header(self):
        r = Client().get('/api/v1/health', HTTP_X_REQUEST_ID='abc12345-from-nginx')
        self.assertEqual(r['X-Request-ID'], 'abc12345-from-nginx')
        self.assertEqual(len(Client().get('/api/v1/health', HTTP_X_REQUEST_ID='bad id!')['X-Request-ID']), 32)

    def test_database_url_parsing(self):
        from sudo_admin.settings import _database_from_url

        cfg = _database_from_url('postgres://sud%40tag:p%3Ass@db.local:6432/sudotag?sslmode=require')
        self.assertEqual(cfg['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual((cfg['USER'], cfg['PASSWORD'], cfg['HOST'], cfg['PORT'], cfg['NAME']),
                         ('sud@tag', 'p:ss', 'db.local', '6432', 'sudotag'))
        self.assertEqual(cfg['OPTIONS'], {'sslmode': 'require'})
        with self.assertRaises(ValueError):
            _database_from_url('mysql://x')
