from django.contrib import admin

from apps.finance.models import (
    CostCenter,
    FinancialCategory,
    FinancialTransaction,
    PaymentMethod,
    PayableAccount,
    ProfessionalCommissionRule,
    ReceivableAccount,
)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "kind", "is_active"]
    list_filter = ["kind", "is_active"]


@admin.register(FinancialCategory)
class FinancialCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "kind", "is_active"]
    list_filter = ["kind", "is_active"]


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "is_active"]


@admin.register(ReceivableAccount)
class ReceivableAccountAdmin(admin.ModelAdmin):
    list_display = ["__str__", "clinic", "due_date", "status"]
    list_filter = ["status"]
    search_fields = ["description", "patient__full_name"]


@admin.register(PayableAccount)
class PayableAccountAdmin(admin.ModelAdmin):
    list_display = ["supplier_name", "clinic", "due_date", "status"]
    list_filter = ["status"]
    search_fields = ["supplier_name", "description"]


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "clinic", "kind", "paid_at"]
    list_filter = ["kind"]


@admin.register(ProfessionalCommissionRule)
class ProfessionalCommissionRuleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "clinic", "is_active"]
