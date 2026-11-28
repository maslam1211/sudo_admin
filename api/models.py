from django.db import models


class RateLimitBucket(models.Model):
    """Fixed-window counter shared by every gunicorn worker.

    The default cache is per-process (LocMemCache), so limits are kept in the
    database instead. One row per limit key, e.g. ``otp-send:phone:+9198…``.
    """

    key = models.CharField(max_length=200, primary_key=True)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'api_rate_limit_bucket'


class PrivateFile(models.Model):
    """A file kept on this server, never on a public URL.

    Vehicle documents (RC, driving licence, insurance, PUC) live here. The
    Firestore ``vehicleDocuments`` row keeps the metadata the app lists; this
    row records where the bytes are and who owns them.
    """

    KIND_VEHICLE_DOCUMENT = 'vehicle_document'

    id = models.CharField(max_length=64, primary_key=True)   # = vehicleDocuments doc id
    kind = models.CharField(max_length=32, default=KIND_VEHICLE_DOCUMENT)
    owner_uid = models.CharField(max_length=128, db_index=True)
    vehicle_id = models.CharField(max_length=128, db_index=True, blank=True, default='')
    storage_path = models.CharField(max_length=512, unique=True)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    legacy_url = models.TextField(blank=True, default='')  # old Cloudinary URL, if copied
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_private_file'


# ─── Phase 1: full mirror of Firebase data on this server ────────────────────
class FirestoreDocument(models.Model):
    """One Firestore document, copied as-is (types tagged, see api.mirror.encode).

    Covers every collection and subcollection. A document that disappears
    from Firestore keeps its last data here with `deleted_at` set, so nothing
    is lost before each domain moves to its own tables (Phase 2/3).
    """

    path = models.CharField(max_length=1024, primary_key=True)        # users/u1/user-settings/u1
    collection_path = models.CharField(max_length=1024, db_index=True)  # users/u1/user-settings
    collection_id = models.CharField(max_length=200, db_index=True)    # user-settings
    doc_id = models.CharField(max_length=512)
    parent_path = models.CharField(max_length=1024, blank=True, default='', db_index=True)
    data = models.JSONField(null=True)       # None = "missing" doc that only holds subcollections
    content_hash = models.CharField(max_length=64, blank=True, default='')
    create_time = models.DateTimeField(null=True)
    update_time = models.DateTimeField(null=True)
    first_synced_at = models.DateTimeField(auto_now_add=True)
    synced_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'mirror_firestore_document'


class FirebaseAuthUser(models.Model):
    """Firebase Auth account (login stays on Firebase). No password hashes."""

    uid = models.CharField(max_length=128, primary_key=True)
    email = models.CharField(max_length=320, blank=True, default='', db_index=True)
    phone_number = models.CharField(max_length=32, blank=True, default='', db_index=True)
    display_name = models.CharField(max_length=256, blank=True, default='')
    photo_url = models.TextField(blank=True, default='')
    email_verified = models.BooleanField(default=False)
    disabled = models.BooleanField(default=False)
    providers = models.JSONField(default=list)          # [{providerId, uid, email, phoneNumber}]
    custom_claims = models.JSONField(null=True)
    created_at = models.DateTimeField(null=True)
    last_sign_in_at = models.DateTimeField(null=True)
    synced_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'mirror_firebase_auth_user'


class FirebaseStorageObject(models.Model):
    """A Firebase Storage file copied under PRIVATE_MEDIA_ROOT/firebase_storage/."""

    path = models.CharField(max_length=1024, primary_key=True)   # civic_evidence/u1/r1/a.jpg
    bucket = models.CharField(max_length=256)
    size_bytes = models.BigIntegerField()
    md5_hash = models.CharField(max_length=64, blank=True, default='')
    content_type = models.CharField(max_length=128, blank=True, default='')
    updated = models.DateTimeField(null=True)
    local_path = models.CharField(max_length=1100)
    synced_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'mirror_firebase_storage_object'


class MirrorRun(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, default='running')   # running | ok | partial | failed
    stats = models.JSONField(default=dict)
    error = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'mirror_run'


# ─── Phase 1: background worker ──────────────────────────────────────────────
class ScheduledJob(models.Model):
    """State of one periodic job (see api.worker.JOBS). The lease stops two
    workers from running the same job at once."""

    name = models.CharField(max_length=64, primary_key=True)
    next_run_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True)
    last_started_at = models.DateTimeField(null=True)
    last_finished_at = models.DateTimeField(null=True)
    last_status = models.CharField(max_length=16, blank=True, default='')
    last_error = models.TextField(blank=True, default='')
    run_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'worker_scheduled_job'


class OutboxEvent(models.Model):
    """Work to do after a database change (replaces Firestore triggers).

    Written in the same transaction as the change; the worker runs the
    handler registered for `topic` and retries with backoff.
    """

    STATUS_PENDING = 'pending'
    STATUS_DONE = 'done'
    STATUS_DEAD = 'dead'

    topic = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, default=STATUS_PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    last_error = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'worker_outbox_event'
        indexes = [models.Index(fields=['status', 'available_at'], name='outbox_due_idx')]
