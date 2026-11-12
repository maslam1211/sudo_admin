from django.db import models


class ArchivedUser(models.Model):
    user_id = models.CharField(max_length=128, db_index=True)
    email = models.CharField(max_length=255, blank=True, default='')
    full_name = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=32, blank=True, default='')
    original_created_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(auto_now_add=True)
    raw = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        display = self.full_name or self.email or self.user_id
        return f"ArchivedUser({display})"


class ArchivedVehicle(models.Model):
    vehicle_id = models.CharField(max_length=128, db_index=True)
    owner_id = models.CharField(max_length=128, db_index=True)
    registration_number = models.CharField(max_length=64, blank=True, default='')
    make = models.CharField(max_length=128, blank=True, default='')
    model = models.CharField(max_length=128, blank=True, default='')
    vehicle_type = models.CharField(max_length=64, blank=True, default='')
    owner_contact = models.CharField(max_length=32, blank=True, default='')
    qr_code_id = models.CharField(max_length=64, blank=True, default='')
    original_created_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(auto_now_add=True)
    raw = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        display = self.registration_number or self.vehicle_id
        return f"ArchivedVehicle({display})"


class CallRouteIntent(models.Model):
    """Pending dial destination per caller (from). DB-backed so multi-worker servers see the same row."""

    caller_key = models.CharField(max_length=10, primary_key=True)
    destination = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'call_route_intent'

    def __str__(self) -> str:
        return f'{self.caller_key}->{self.destination}'


class ActivationEmailOtp(models.Model):
    """
    One emailed 6-digit code for the web QR-activation flow (activate-id).

    Only an HMAC of the code is stored. Rows double as the send log used for
    per-email and per-IP rate limits, so they live in the shared DB rather than
    the per-process cache.
    """

    email = models.CharField(max_length=255, db_index=True)
    qr_id = models.CharField(max_length=64)
    code_hash = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed = models.BooleanField(default=False)

    class Meta:
        db_table = 'activation_email_otp'

    def __str__(self) -> str:
        return f'ActivationEmailOtp({self.qr_id}, consumed={self.consumed})'
