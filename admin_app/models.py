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
    """Short-lived mapping from scanner caller (10 digits) to PBX destination."""

    caller_key = models.CharField(max_length=10, unique=True, db_index=True)
    destination = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'CallRouteIntent({self.caller_key} -> {self.destination})'
