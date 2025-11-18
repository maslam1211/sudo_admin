from django.contrib import admin
from .models import ArchivedUser, ArchivedVehicle, MaskedCallSession


@admin.register(ArchivedUser)
class ArchivedUserAdmin(admin.ModelAdmin):
    list_display = ("user_id", "full_name", "email", "phone", "archived_at")
    search_fields = ("user_id", "full_name", "email", "phone")
    list_filter = ("archived_at",)
    ordering = ("-archived_at",)


@admin.register(ArchivedVehicle)
class ArchivedVehicleAdmin(admin.ModelAdmin):
    list_display = ("vehicle_id", "owner_id", "registration_number", "make", "model", "archived_at")
    search_fields = ("vehicle_id", "owner_id", "registration_number", "make", "model", "qr_code_id")
    list_filter = ("archived_at", "make", "model", "vehicle_type")
    ordering = ("-archived_at",)


@admin.register(MaskedCallSession)
class MaskedCallSessionAdmin(admin.ModelAdmin):
    list_display = ("session_id", "masked_number", "receiver_real_number", "status", "created_at", "expires_at")
    search_fields = ("session_id", "masked_number", "receiver_real_number", "caller_real_number", "qr_id")
    list_filter = ("status", "created_at", "expires_at")
    ordering = ("-created_at",)
    readonly_fields = ("session_id", "created_at")
    
    fieldsets = (
        ("Session Info", {
            "fields": ("session_id", "status", "created_at", "expires_at")
        }),
        ("Numbers (Privacy Protected)", {
            "fields": ("masked_number", "caller_real_number", "receiver_real_number"),
            "description": "Masked number is what receiver sees. Real numbers are hidden for privacy."
        }),
        ("Call Details", {
            "fields": ("qr_id", "reason", "call_sid")
        }),
    )
