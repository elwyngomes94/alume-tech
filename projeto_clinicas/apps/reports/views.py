"""Views de relatorios da clinica."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.audit.models import AuditAction
from apps.audit.services import log_action, log_denied
from apps.core.mixins import ClinicViewMixin
from apps.core.utils import period_range
from apps.reports import services
from apps.reports.exporters import export


def _assert_report_access(request, key: str) -> None:
    """
    Relatorios financeiros exigem 'finance.report.view' alem do
    'report.view'/'report.export' generico ja checado pelo ClinicViewMixin.
    """
    if key in services.FINANCE_REPORT_KEYS and not request.user.has_clinic_perm(
        "finance.report.view", request.clinic
    ):
        log_denied(f"Permissao 'finance.report.view' negada para o relatorio '{key}'", request=request)
        raise PermissionDenied("Voce nao possui permissao para acessar relatorios financeiros.")


class ReportHomeView(ClinicViewMixin, TemplateView):
    template_name = "reports/home.html"
    required_permission = "report.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start, end = period_range(
            self.request.GET.get("period", "30d"),
            self.request.GET.get("start", ""),
            self.request.GET.get("end", ""),
        )
        context["start"] = start
        context["end"] = end
        context["period"] = self.request.GET.get("period", "30d")
        can_see_finance = self.request.user.has_clinic_perm(
            "finance.report.view", self.request.clinic
        )
        context["reports"] = [
            (key, label)
            for key, (label, _fn) in services.REPORTS.items()
            if can_see_finance or key not in services.FINANCE_REPORT_KEYS
        ]
        context["indicators"] = services.indicators(start, end)
        return context


class ReportDetailView(ClinicViewMixin, TemplateView):
    template_name = "reports/detail.html"
    required_permission = "report.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        key = self.kwargs["report"]
        if key not in services.REPORTS:
            raise Http404("Relatorio inexistente.")
        _assert_report_access(self.request, key)
        label, function = services.REPORTS[key]
        start, end = period_range(
            self.request.GET.get("period", "30d"),
            self.request.GET.get("start", ""),
            self.request.GET.get("end", ""),
        )
        kwargs_extra = {}
        if key == "agendamentos":
            kwargs_extra = {
                "professional": self.request.GET.get("professional", ""),
                "status": self.request.GET.get("status", ""),
            }
        headers, rows = function(start, end, **kwargs_extra)
        query = f"?period={self.request.GET.get('period', '30d')}&start={start:%Y-%m-%d}&end={end:%Y-%m-%d}"
        context.update(
            {
                "report_key": key,
                "report_label": label,
                "headers": headers,
                "rows": rows,
                "start": start,
                "end": end,
                "period": self.request.GET.get("period", "30d"),
                "total_rows": len(rows),
                "pdf_url": reverse("reports:export", args=[key, "pdf"]) + query,
                "excel_url": reverse("reports:export", args=[key, "xlsx"]) + query,
                "whatsapp_text": f"Ola! Segue o relatorio de {label.lower()} da clinica "
                f"{self.request.clinic}.",
            }
        )
        return context


class ReportExportView(ClinicViewMixin, View):
    required_permission = "report.export"

    def get(self, request, report, fmt):
        if report not in services.REPORTS:
            raise Http404("Relatorio inexistente.")
        _assert_report_access(request, report)
        label, function = services.REPORTS[report]
        start, end = period_range(
            request.GET.get("period", "30d"),
            request.GET.get("start", ""),
            request.GET.get("end", ""),
        )
        kwargs_extra = {}
        if report == "agendamentos":
            kwargs_extra = {
                "professional": request.GET.get("professional", ""),
                "status": request.GET.get("status", ""),
            }
        headers, rows = function(start, end, **kwargs_extra)

        log_action(
            AuditAction.EXPORT,
            description=f"Exportacao do relatorio '{label}' ({fmt}) - "
            f"{start:%d/%m/%Y} a {end:%d/%m/%Y}",
            request=request,
            object_type="reports.Report",
            object_repr=label,
            is_sensitive=True,
        )
        filename = f"jja-{report}-{start:%Y%m%d}-{end:%Y%m%d}"
        subtitle = (
            f"{request.clinic} | Periodo: {start:%d/%m/%Y} a {end:%d/%m/%Y}"
        )
        return export(fmt, filename, headers, rows, title=label, subtitle=subtitle, clinic=request.clinic)
