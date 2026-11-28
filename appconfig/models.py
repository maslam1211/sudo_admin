"""App version policy (appConfig/{platform}), release history and update events.

`document` keeps the full Firestore document (types tagged by
api.mirror.encode). The admin panel still publishes to Firestore (the
`onAppVersionPublished` function sends the update push from there), and each
publish is imported here at once; the app reads only from here.
"""

from django.db import models


class AppConfig(models.Model):
    platform = models.CharField(max_length=16, primary_key=True)   # android | ios
    latest_version = models.CharField(max_length=40, blank=True, default='')
    latest_build = models.IntegerField(default=0)
    min_supported_build = models.IntegerField(default=0)
    update_enabled = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True)
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'appconfig_app_config'


class AppRelease(models.Model):
    """appConfig/{platform}/releases/{id}."""

    id = models.CharField(max_length=128, primary_key=True)
    platform = models.CharField(max_length=16, db_index=True)
    latest_build = models.IntegerField(default=0)
    published_at = models.DateTimeField(null=True, db_index=True)
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'appconfig_app_release'


class AppUpdateEvent(models.Model):
    """app_update_events: one row per update-check event from the app.

    `id` is the Firestore document id for events written by older builds,
    or `api-<n>` for events posted to the API.
    """

    id = models.CharField(max_length=128, primary_key=True)
    uid = models.CharField(max_length=128, blank=True, default='', db_index=True)
    platform = models.CharField(max_length=16, db_index=True)
    event = models.CharField(max_length=40)
    version = models.CharField(max_length=40, blank=True, default='')
    build = models.IntegerField(default=0)
    target_build = models.IntegerField(null=True)
    urgency = models.CharField(max_length=16, blank=True, default='')
    error = models.CharField(max_length=500, blank=True, default='')
    from_build = models.IntegerField(null=True)
    created_at = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=10, default='firestore')   # firestore | api

    class Meta:
        db_table = 'appconfig_app_update_event'
        indexes = [models.Index(fields=['platform', '-created_at'], name='update_event_recent_idx')]
