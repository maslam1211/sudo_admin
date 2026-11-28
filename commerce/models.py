"""Checkout data in PostgreSQL.

Every row keeps the complete Firestore-shaped document in `document`
(types tagged with api.mirror.encode) plus typed columns for what is
queried. `master` says where the record is edited:

    'postgres'  created through the API: this row is the truth and is copied
                to Firestore (partner commissions, admin panel, old builds).
    'firestore' written by old app builds, the website or the admin panel:
                imported from Firestore (commerce.sync) until those writers
                are switched over.
"""

from django.db import models

MASTER_POSTGRES = 'postgres'
MASTER_FIRESTORE = 'firestore'
MASTER_CHOICES = [(MASTER_POSTGRES, 'PostgreSQL'), (MASTER_FIRESTORE, 'Firestore')]


class CheckoutSettings(models.Model):
    """web_checkout_settings/{id} — prices, shipping, buying open/closed, plan prices."""

    id = models.CharField(max_length=64, primary_key=True, default='default')
    document = models.JSONField(default=dict)
    master = models.CharField(max_length=10, choices=MASTER_CHOICES, default=MASTER_FIRESTORE)
    synced_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'commerce_checkout_settings'


class Coupon(models.Model):
    """web_coupons/{CODE}."""

    code = models.CharField(max_length=32, primary_key=True)
    active = models.BooleanField(default=False)
    discount_type = models.CharField(max_length=16, blank=True, default='')
    discount_value = models.FloatField(null=True)
    min_quantity = models.FloatField(null=True)
    max_uses = models.FloatField(null=True)
    used_count = models.FloatField(default=0)
    expires_at = models.DateTimeField(null=True)
    document = models.JSONField(default=dict)
    master = models.CharField(max_length=10, choices=MASTER_CHOICES, default=MASTER_FIRESTORE)
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'commerce_coupon'


class Order(models.Model):
    """orders/{id} — same id as the Firestore document."""

    id = models.CharField(max_length=128, primary_key=True)
    user_id = models.CharField(max_length=128, db_index=True)
    payment_status = models.CharField(max_length=32, blank=True, default='', db_index=True)
    payment_verified = models.BooleanField(default=False)
    order_status = models.IntegerField(default=0, db_index=True)
    razorpay_order_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    amount = models.FloatField(default=0)
    quantity = models.IntegerField(default=1)
    selected_item = models.CharField(max_length=64, blank=True, default='')
    coupon_code = models.CharField(max_length=32, blank=True, default='')
    partner_code = models.CharField(max_length=64, blank=True, default='', db_index=True)
    qr_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    source = models.CharField(max_length=32, blank=True, default='')
    placed_at = models.DateTimeField(null=True, db_index=True)   # document.timestamp
    document = models.JSONField(default=dict)
    master = models.CharField(max_length=10, choices=MASTER_CHOICES, default=MASTER_FIRESTORE)
    synced_at = models.DateTimeField(null=True)
    projected_at = models.DateTimeField(null=True)              # last copy written to Firestore
    deleted_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'commerce_order'
        indexes = [models.Index(fields=['user_id', '-placed_at'], name='order_user_recent_idx')]


class Payment(models.Model):
    """payments/{id} — Cloud Function rows use the Razorpay payment id as id."""

    id = models.CharField(max_length=128, primary_key=True)
    razorpay_payment_id = models.CharField(max_length=64, db_index=True)
    razorpay_order_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    order_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    user_id = models.CharField(max_length=128, blank=True, default='')
    amount_paise = models.BigIntegerField(null=True)
    verified = models.BooleanField(default=False)
    verification_method = models.CharField(max_length=16, blank=True, default='')
    document = models.JSONField(default=dict)
    master = models.CharField(max_length=10, choices=MASTER_CHOICES, default=MASTER_FIRESTORE)
    synced_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'commerce_payment'


class PaymentClaim(models.Model):
    """payment_claims/{paymentId}: one Razorpay payment pays for one purpose."""

    payment_id = models.CharField(max_length=64, primary_key=True)
    purpose = models.CharField(max_length=160)       # order:<razorpayOrderId>, fleet:…, product:…
    uid = models.CharField(max_length=128, blank=True, default='')
    claimed_at = models.DateTimeField()
    master = models.CharField(max_length=10, choices=MASTER_CHOICES, default=MASTER_FIRESTORE)

    class Meta:
        db_table = 'commerce_payment_claim'
