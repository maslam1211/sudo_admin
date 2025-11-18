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


class MaskedCallSession(models.Model):
    """
    Tracks number masking sessions for privacy protection.
    Similar to NGF132/Sampark system where both parties see masked numbers.
    """
    session_id = models.CharField(max_length=64, unique=True, db_index=True)
    masked_number = models.CharField(max_length=32, db_index=True)  # The number receiver sees
    caller_real_number = models.CharField(max_length=32, blank=True, default='')  # Caller's number (hidden)
    receiver_real_number = models.CharField(max_length=32, db_index=True)  # Owner's number (hidden)
    qr_id = models.CharField(max_length=64, blank=True, default='')
    reason = models.TextField(blank=True, default='')
    call_sid = models.CharField(max_length=64, blank=True, default='')  # Twilio call SID
    status = models.CharField(max_length=32, default='initiated')  # initiated, connected, completed, expired
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Session expires after some time
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session_id']),
            models.Index(fields=['masked_number']),
            models.Index(fields=['receiver_real_number']),
        ]
    
    def __str__(self):
        return f"MaskedCallSession({self.session_id}): {self.masked_number}"
    
    def is_expired(self):
        from django.utils import timezone
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
