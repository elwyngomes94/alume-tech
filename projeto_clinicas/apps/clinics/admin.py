from django.contrib import admin

from apps.clinics.models import (
    Clinic,
    ClinicSettings,
    InsurancePlan,
    Room,
    Service,
    Specialty,
)


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ["trade_name", "clinic_type", "status", "city", "state", "created_at"]
    list_filter = ["clinic_type", "status"]
    search_fields = ["trade_name", "legal_name", "document"]
    prepopulated_fields = {"slug": ("trade_name",)}


@admin.register(ClinicSettings)
class ClinicSettingsAdmin(admin.ModelAdmin):
    list_display = ["clinic"]


@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "is_active"]
    list_filter = ["is_active"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "duration_minutes", "price", "is_active"]
    list_filter = ["is_active"]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "is_active"]


@admin.register(InsurancePlan)
class InsurancePlanAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "is_active"]
