from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["record_number", "full_name", "clinic", "status", "created_at"]
    list_filter = ["status", "clinic"]
    search_fields = ["full_name", "cpf", "email"]
