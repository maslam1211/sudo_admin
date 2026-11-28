"""Referral data in PostgreSQL.

Same records as Firestore, keyed by the same ids:

    referralCodes/{CODE}     -> ReferralCode
    referrals/{referredUid}  -> Referral
    users/{uid}.referralCode, referredByCode, referredByUserId, referralStats
                             -> ReferralProfile

Writes still run as a Firestore transaction: the users and vehicles
triggers (onUserCreatedAssignReferralCode, onVehicleCreatedMarkReferralSuccessful)
and older app builds change the same documents, and the transaction is what
stops a referral being applied twice. Every API write is copied here at once,
and the worker imports what the Cloud Functions wrote. Firestore stays the
write lock until users and vehicles move to PostgreSQL.

`document` keeps the full Firestore document (types tagged by api.mirror.encode).
"""

from django.db import models


class ReferralCode(models.Model):
    code = models.CharField(max_length=32, primary_key=True)
    user_id = models.CharField(max_length=128, db_index=True)
    user_name = models.CharField(max_length=200, blank=True, default='')
    contact_number = models.CharField(max_length=40, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(null=True)
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'referrals_code'


class Referral(models.Model):
    id = models.CharField(max_length=128, primary_key=True)             # referred user's uid
    referrer_user_id = models.CharField(max_length=128, db_index=True)
    referred_user_id = models.CharField(max_length=128, db_index=True)
    referral_code = models.CharField(max_length=32, blank=True, default='', db_index=True)
    status = models.CharField(max_length=16, blank=True, default='', db_index=True)
    reward_status = models.CharField(max_length=16, blank=True, default='')
    reward_amount = models.FloatField(default=0)
    registered_at = models.DateTimeField(null=True, db_index=True)
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'referrals_referral'
        indexes = [models.Index(fields=['referrer_user_id', '-registered_at'], name='referral_by_referrer_idx')]


class ReferralProfile(models.Model):
    """The referral fields of users/{uid}; `stats` is referralStats as stored."""

    user_id = models.CharField(max_length=128, primary_key=True)
    referral_code = models.CharField(max_length=32, blank=True, default='', db_index=True)
    referred_by_code = models.CharField(max_length=32, blank=True, default='')
    referred_by_user_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    stats = models.JSONField(null=True)
    total_referrals = models.IntegerField(default=0)
    successful_referrals = models.IntegerField(default=0)
    full_name = models.CharField(max_length=200, blank=True, default='')
    contact_number = models.CharField(max_length=40, blank=True, default='')
    email_address = models.CharField(max_length=254, blank=True, default='')
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)                         # users/{uid} removed

    class Meta:
        db_table = 'referrals_profile'


class ReferralImport(models.Model):
    """One row once a full import has finished; admin reads PostgreSQL after that."""

    id = models.CharField(max_length=16, primary_key=True, default='full')
    finished_at = models.DateTimeField()

    class Meta:
        db_table = 'referrals_import'
