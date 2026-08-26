from django.contrib import admin

from apps.tenants.models import ClinicMembership, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "trade_name", "is_active"]


@admin.register(ClinicMembership)
class ClinicMembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "clinic", "role", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["user__email", "clinic__trade_name"]
