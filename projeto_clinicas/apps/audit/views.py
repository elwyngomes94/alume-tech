"""Consulta da trilha de auditoria pela clinica."""
from __future__ import annotations

from django.db.models import Q
from django.views.generic import ListView

from apps.audit.models import AuditAction, AuditLog
from apps.core.mixins import ClinicViewMixin
from apps.core.utils import parse_date


class AuditLogListView(ClinicViewMixin, ListView):
    """
    Auditoria da clinica ativa.

    O administrador local so enxerga eventos da propria clinica: o filtro por
    ``clinic`` e aplicado no queryset, nunca vindo da querystring.
    """

    model = AuditLog
    template_name = "audit/audit_list.html"
    context_object_name = "logs"
    paginate_by = 50
    required_permission = "audit.view"

    def get_queryset(self):
        queryset = AuditLog.objects.filter(clinic=self.request.clinic).select_related("user")
        action = self.request.GET.get("action", "")
        if action:
            queryset = queryset.filter(action=action)
        user = self.request.GET.get("user", "")
        if user:
            queryset = queryset.filter(user_email__icontains=user)
        start = parse_date(self.request.GET.get("start", ""))
        if start:
            queryset = queryset.filter(created_at__date__gte=start)
        end = parse_date(self.request.GET.get("end", ""))
        if end:
            queryset = queryset.filter(created_at__date__lte=end)
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(object_repr__icontains=search) | Q(description__icontains=search)
            )
        if self.request.GET.get("sensitive") == "1":
            queryset = queryset.filter(is_sensitive=True)
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["actions"] = AuditAction.choices
        return context
