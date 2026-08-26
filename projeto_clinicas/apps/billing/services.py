"""Controle de limites do plano contratado."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.core.exceptions import ValidationError


@dataclass
class LimitStatus:
    resource: str
    used: int
    limit: int

    @property
    def unlimited(self) -> bool:
        return self.limit == 0

    @property
    def exceeded(self) -> bool:
        return not self.unlimited and self.used >= self.limit

    @property
    def percent(self) -> int:
        if self.unlimited or self.limit == 0:
            return 0
        return min(100, int(self.used * 100 / self.limit))


def get_subscription(clinic):
    return getattr(clinic, "subscription", None)


def current_usage(clinic, resource: str) -> int:
    from apps.core.tenancy import tenant_context
    from apps.documents.models import Document
    from apps.patients.models import Patient
    from apps.professionals.models import Professional
    from apps.tenants.models import ClinicMembership

    with tenant_context(clinic):
        if resource == "professionals":
            return Professional.objects.filter(is_active=True).count()
        if resource == "patients":
            return Patient.objects.count()
        if resource == "users":
            return ClinicMembership.all_objects.filter(
                clinic=clinic, is_active=True, is_deleted=False
            ).count()
        if resource == "storage":
            total = sum(Document.objects.values_list("size", flat=True))
            return int(total / 1048576)
    return 0


def limit_status(clinic, resource: str) -> Optional[LimitStatus]:
    subscription = get_subscription(clinic)
    if subscription is None:
        return None
    return LimitStatus(
        resource=resource,
        used=current_usage(clinic, resource),
        limit=subscription.plan.limit_for(resource),
    )


def assert_within_limit(clinic, resource: str) -> None:
    """Bloqueia a criacao de novos registros quando o plano ja atingiu o limite."""
    status = limit_status(clinic, resource)
    if status is None or status.unlimited:
        return
    if status.exceeded:
        raise ValidationError(
            f"Limite do plano atingido para '{resource}' "
            f"({status.used}/{status.limit}). Atualize o plano para continuar."
        )


def clinic_limits(clinic) -> list:
    return [
        status
        for status in (
            limit_status(clinic, resource)
            for resource in ("professionals", "users", "patients", "storage")
        )
        if status is not None
    ]


# ---------------------------------------------------------------------------
# Financeiro do sistema (exclusivo do SUPERADMIN)
# ---------------------------------------------------------------------------
def system_financial_metrics(start=None, end=None) -> dict:
    """
    Contabilidade da propria plataforma JJA System.

    Segue o mesmo padrao de ``apps.platform_admin.services.platform_metrics``:
    agrega todas as clinicas usando ``unscoped()``.
    """
    from decimal import Decimal

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    from apps.billing.models import Invoice, Payment, SystemExpense, Subscription
    from apps.clinics.models import Clinic
    from apps.core.tenancy import unscoped

    ZERO = Decimal("0.00")

    with unscoped("financeiro do sistema"):
        payments = Payment.objects.all()
        if start and end:
            payments = payments.filter(paid_at__date__gte=start, paid_at__date__lte=end)
        period_revenue = payments.aggregate(total=Sum("amount"))["total"] or ZERO

        today = timezone.localdate()
        active_monthly_prices = (
            Subscription.objects.filter(status=Subscription.Status.ACTIVE)
            .values_list("plan__monthly_price", flat=True)
        )
        mrr_total = sum((price or ZERO for price in active_monthly_prices), ZERO)

        subscriptions = Subscription.objects.all()
        expenses = SystemExpense.objects.all()
        if start and end:
            expenses = expenses.filter(expense_date__gte=start, expense_date__lte=end)
        expense_total = expenses.aggregate(total=Sum("amount"))["total"] or ZERO

        overdue_invoices = Invoice.objects.filter(
            status=Invoice.Status.OPEN, due_date__lt=today
        )

        revenue_by_plan = list(
            payments.values("invoice__subscription__plan__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )
        revenue_by_clinic = list(
            payments.values("invoice__subscription__clinic__trade_name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:10]
        )
        monthly_growth = list(
            Payment.objects.annotate(month=TruncMonth("paid_at"))
            .values("month")
            .annotate(total=Sum("amount"))
            .order_by("month")
        )

        metrics = {
            "period_revenue": period_revenue,
            "mrr": mrr_total,
            "arr": mrr_total * 12,
            "expense_total": expense_total,
            "profit": period_revenue - expense_total,
            "margin_percent": (
                round(((period_revenue - expense_total) / period_revenue) * 100, 1)
                if period_revenue
                else 0.0
            ),
            "subscriptions_active": subscriptions.filter(
                status=Subscription.Status.ACTIVE
            ).count(),
            "subscriptions_trial": subscriptions.filter(
                status=Subscription.Status.TRIAL
            ).count(),
            "subscriptions_past_due": subscriptions.filter(
                status=Subscription.Status.PAST_DUE
            ).count(),
            "subscriptions_canceled": subscriptions.filter(
                status=Subscription.Status.CANCELED
            ).count(),
            "overdue_invoices_count": overdue_invoices.count(),
            "overdue_amount": overdue_invoices.aggregate(total=Sum("amount"))["total"] or ZERO,
            "clinics_total": Clinic.objects.count(),
            "average_ticket": (
                round(period_revenue / payments.count(), 2) if payments.count() else ZERO
            ),
            "revenue_by_plan": revenue_by_plan,
            "revenue_by_clinic": revenue_by_clinic,
            "chart_growth_labels": [m["month"].strftime("%m/%Y") for m in monthly_growth],
            "chart_growth_values": [float(m["total"] or 0) for m in monthly_growth],
        }
    return metrics
