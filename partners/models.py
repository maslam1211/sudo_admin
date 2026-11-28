"""Partner Programme data in PostgreSQL — a read copy.

The money rules (commissions, the hold, reversals, withdrawals, target
bonuses) stay in functions/partner_programme.js and partner_activation.js,
and Firestore stays the source of truth, until orders no longer depend on
Firestore. These tables are filled by partners.sync: every few minutes by
the worker, and at once after each admin decision.

    partnerProgram/config, counters/partnerIds -> PartnerSetting (by path)
    partners/{uid}                             -> Partner
    partners/{uid}/private/payout              -> PartnerPayout
    partners/{uid}/ledger/{id}                 -> PartnerLedgerEntry ("{uid}/{id}")
    partnerCodes/{CODE}                        -> PartnerCode
    partnerCommissions/{id}                    -> PartnerCommission
    partnerWithdrawals/{id}                    -> PartnerWithdrawal
    partnerActivationClaims/{id}               -> PartnerActivationClaim
    partner_admin_audit/{id}                   -> PartnerAdminAudit

partnerSecrets (activation passcode hashes) is not copied: only the Cloud
Function reads it, and the Phase 1 mirror already backs it up.

`document` keeps the full Firestore document (types tagged by api.mirror.encode).
"""

from django.db import models


class Copied(models.Model):
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        abstract = True


class PartnerSetting(Copied):
    path = models.CharField(max_length=128, primary_key=True)

    class Meta:
        db_table = 'partners_setting'


class Partner(Copied):
    uid = models.CharField(max_length=128, primary_key=True)
    partner_id = models.CharField(max_length=32, blank=True, default='', db_index=True)
    name = models.CharField(max_length=200, blank=True, default='')
    phone = models.CharField(max_length=40, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=16, blank=True, default='', db_index=True)
    wallet_available = models.IntegerField(default=0)
    wallet_pending = models.IntegerField(default=0)
    wallet_on_hold = models.IntegerField(default=0)
    wallet_paid = models.IntegerField(default=0)
    wallet_lifetime = models.IntegerField(default=0)
    applied_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'partners_partner'


class PartnerPayout(Copied):
    """UPI / bank details. Admin-only, like the Firestore document."""

    uid = models.CharField(max_length=128, primary_key=True)

    class Meta:
        db_table = 'partners_payout'


class PartnerLedgerEntry(Copied):
    id = models.CharField(max_length=300, primary_key=True)        # "{uid}/{ledger doc id}"
    partner_uid = models.CharField(max_length=128, db_index=True)
    type = models.CharField(max_length=40, blank=True, default='')
    amount = models.IntegerField(default=0)
    ref = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'partners_ledger_entry'


class PartnerCode(Copied):
    code = models.CharField(max_length=32, primary_key=True)
    partner_uid = models.CharField(max_length=128, db_index=True)
    active = models.BooleanField(default=False)

    class Meta:
        db_table = 'partners_code'


class PartnerCommission(Copied):
    id = models.CharField(max_length=200, primary_key=True)        # order id, or act_{col}_{qrId}
    partner_uid = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=16, blank=True, default='', db_index=True)
    amount = models.IntegerField(default=0)
    quantity = models.IntegerField(default=0)
    source = models.CharField(max_length=32, blank=True, default='')
    created_at = models.DateTimeField(null=True, db_index=True)
    available_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'partners_commission'


class PartnerWithdrawal(Copied):
    id = models.CharField(max_length=128, primary_key=True)
    partner_uid = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=16, blank=True, default='', db_index=True)
    amount = models.IntegerField(default=0)
    requested_at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'partners_withdrawal'


class PartnerActivationClaim(Copied):
    id = models.CharField(max_length=200, primary_key=True)
    partner_uid = models.CharField(max_length=128, blank=True, default='', db_index=True)
    status = models.CharField(max_length=16, blank=True, default='')

    class Meta:
        db_table = 'partners_activation_claim'


class PartnerAdminAudit(Copied):
    id = models.CharField(max_length=128, primary_key=True)
    kind = models.CharField(max_length=32, blank=True, default='')
    action = models.CharField(max_length=32, blank=True, default='')
    at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'partners_admin_audit'


class PartnerImport(models.Model):
    """One row once a full import has finished; admin lists read PostgreSQL after that."""

    id = models.CharField(max_length=16, primary_key=True, default='full')
    finished_at = models.DateTimeField()

    class Meta:
        db_table = 'partners_import'
