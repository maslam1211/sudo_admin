"""User data in PostgreSQL (Phase 4a).

    users/{uid}                    -> UserProfile
    users/{uid}/user-settings/{id} -> UserSettings (one per user, id == uid)
    users/{uid}/<any other sub>/…  -> UserSubDocument (found by listing, so a
                                      subcollection nobody knew about is still copied)
    blocked_users/{id}             -> BlockedUser
    family_members/{id}            -> FamilyMember
    daily_usage/{uid}              -> DailyUsage

Every row keeps the complete Firestore document in `document` (types tagged
by api.mirror.encode) plus typed columns for lookups. Rows whose Firestore
document disappears are kept with `deleted_at` set.

Firestore stays the source of truth until the app writes through the API;
then `master` = 'postgres' rows are written here first and copied to
Firestore, which Cloud Functions, security rules and other users' apps
still read. Realtime fields (presence, active device, FCM token, live
location) stay Firestore-first until the realtime phase.
"""

from django.db import models

MASTER_POSTGRES = 'postgres'
MASTER_FIRESTORE = 'firestore'
MASTER_CHOICES = [(MASTER_POSTGRES, 'PostgreSQL'), (MASTER_FIRESTORE, 'Firestore')]


class Copied(models.Model):
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        abstract = True


class UserProfile(Copied):
    uid = models.CharField(max_length=128, primary_key=True)
    full_name = models.CharField(max_length=200, blank=True, default='')
    contact_number = models.CharField(max_length=40, blank=True, default='', db_index=True)
    email_address = models.CharField(max_length=254, blank=True, default='', db_index=True)
    city = models.CharField(max_length=100, blank=True, default='')
    profile_picture = models.URLField(max_length=1000, blank=True, default='')
    role_id = models.CharField(max_length=32, blank=True, default='')
    profile_complete = models.BooleanField(default=False)
    account_deleted = models.BooleanField(default=False)
    app_platform = models.CharField(max_length=16, blank=True, default='')
    app_build = models.IntegerField(null=True)
    created_at = models.DateTimeField(null=True, db_index=True)
    master = models.CharField(max_length=10, choices=MASTER_CHOICES, default=MASTER_FIRESTORE)

    class Meta:
        db_table = 'accounts_user_profile'


class UserSettings(Copied):
    uid = models.CharField(max_length=128, primary_key=True)
    doc_id = models.CharField(max_length=128, default='')     # always uid today; kept in case not
    enable_call = models.BooleanField(null=True)
    enable_chat = models.BooleanField(null=True)
    enable_normal_call = models.BooleanField(null=True)
    enable_push_notification = models.BooleanField(null=True)
    enable_sms = models.BooleanField(null=True)
    show_mobile_number = models.BooleanField(null=True)
    show_profile_picture = models.BooleanField(null=True)
    show_vehicle_image = models.BooleanField(null=True)

    class Meta:
        db_table = 'accounts_user_settings'


class UserSubDocument(Copied):
    path = models.CharField(max_length=500, primary_key=True)  # users/{uid}/{sub}/{id}[/...]
    uid = models.CharField(max_length=128, db_index=True)
    subcollection = models.CharField(max_length=128, db_index=True)

    class Meta:
        db_table = 'accounts_user_subdocument'


class BlockedUser(Copied):
    id = models.CharField(max_length=128, primary_key=True)
    blocker_id = models.CharField(max_length=128, db_index=True)
    blocked_user_id = models.CharField(max_length=128, db_index=True)
    blocked_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'accounts_blocked_user'


class FamilyMember(Copied):
    id = models.CharField(max_length=128, primary_key=True)
    owner_id = models.CharField(max_length=128, db_index=True)
    name = models.CharField(max_length=200, blank=True, default='')
    contact_number = models.CharField(max_length=40, blank=True, default='')
    created_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'accounts_family_member'


class DailyUsage(Copied):
    uid = models.CharField(max_length=128, primary_key=True)

    class Meta:
        db_table = 'accounts_daily_usage'


class AccountsImport(models.Model):
    id = models.CharField(max_length=16, primary_key=True, default='full')
    finished_at = models.DateTimeField()

    class Meta:
        db_table = 'accounts_import'
