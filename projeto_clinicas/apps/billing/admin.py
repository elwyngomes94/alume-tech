from django.contrib import admin

from apps.billing.models import Invoice, Payment, Plan, Subscription, SystemExpense


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "tier", "monthly_price", "is_active"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["clinic", "plan", "status", "cycle"]
    list_filter = ["status", "cycle"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["number", "subscription", "amount", "due_date", "status"]
    list_filter = ["status"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["invoice", "amount", "method", "paid_at"]


@admin.register(SystemExpense)
class SystemExpenseAdmin(admin.ModelAdmin):
    list_display = ["description", "category", "amount", "expense_date", "is_recurring"]
    list_filter = ["category", "is_recurring"]
