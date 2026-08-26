from django.contrib import admin

from apps.automation.models import Automation, AutomationExecution, AutomationSettings


@admin.register(Automation)
class AutomationAdmin(admin.ModelAdmin):
    list_display = ["codename", "name", "layer"]
    list_filter = ["layer"]
    search_fields = ["codename", "name"]


@admin.register(AutomationSettings)
class AutomationSettingsAdmin(admin.ModelAdmin):
    list_display = ["clinic", "waiting_list_auto_invite", "auto_generate_receipt",
                     "financial_webhook_enabled"]
    search_fields = ["clinic__trade_name"]


@admin.register(AutomationExecution)
class AutomationExecutionAdmin(admin.ModelAdmin):
    list_display = ["automation", "clinic", "status", "attempts", "started_at"]
    list_filter = ["status", "automation"]
    search_fields = ["clinic__trade_name", "idempotency_key"]
    readonly_fields = [f.name for f in AutomationExecution._meta.fields]
