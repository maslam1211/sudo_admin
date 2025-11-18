from django.contrib import admin
from .models import ArchivedUser, ArchivedVehicle


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
