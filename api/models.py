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
