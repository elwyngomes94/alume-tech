"""Dashboards da clinica e do profissional, alem da busca global contextual."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.permissions import Roles
from apps.core.mixins import ClinicRequiredMixin, ClinicViewMixin
from apps.core.utils import period_range
from apps.scheduling.models import Appointment


class DashboardHomeView(ClinicRequiredMixin, TemplateView):
    """Escolhe o painel conforme o perfil do usuario na clinica ativa."""

    def get(self, request, *args, **kwargs):
        role = request.user.role_in(request.clinic)
        if role == Roles.PROFESSIONAL:
            return redirect("dashboard:professional")
        if role == Roles.RECEPTIONIST:
            return redirect("dashboard:reception")
        return redirect("dashboard:clinic")

    def get_template_names(self):  # pragma: no cover - nunca renderiza
        return ["dashboard/clinic.html"]


class ClinicDashboardView(ClinicViewMixin, TemplateView):
    template_name = "dashboard/clinic.html"
    required_permission = "clinic.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.documents.models import Document
        from apps.examinations.models import ExaminationRequest
        from apps.patients.models import Patient
        from apps.professionals.models import Professional
        from apps.scheduling.services import agenda_summary

        today = timezone.localdate()
        start, end = period_range(self.request.GET.get("period", "30d"))

        appointments = Appointment.objects.filter(
            start_at__date__gte=start, start_at__date__lte=end
        )
        today_appointments = (
            Appointment.objects.filter(start_at__date=today)
            .select_related("patient", "professional", "service")
            .order_by("start_at")
        )

        by_day = (
            appointments.annotate(day=TruncDate("start_at"))
            .values("day")
            .annotate(total=Count("id"))
            .order_by("day")
        )
        by_status = appointments.values("status").annotate(total=Count("id"))
        status_labels = dict(Appointment.Status.choices)

        top_professionals = (
            appointments.values("professional__full_name")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        )
        top_services = (
            appointments.exclude(service__isnull=True)
            .values("service__name")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        )

        context.update(
            {
                "period": self.request.GET.get("period", "30d"),
                "start": start,
                "end": end,
                "total_patients": Patient.objects.count(),
                "new_patients": Patient.objects.filter(
                    created_at__date__gte=start, created_at__date__lte=end
                ).count(),
                "total_professionals": Professional.objects.filter(is_active=True).count(),
                "today_summary": agenda_summary(self.request.clinic, today),
                "today_appointments": today_appointments[:12],
                "next_appointments": Appointment.objects.filter(
                    start_at__gt=timezone.now(),
                    status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
                )
                .select_related("patient", "professional")
                .order_by("start_at")[:8],
                "period_total": appointments.count(),
                "period_completed": appointments.filter(
                    status=Appointment.Status.COMPLETED
                ).count(),
                "period_canceled": appointments.filter(
                    status=Appointment.Status.CANCELED
                ).count(),
                "period_no_show": appointments.filter(status=Appointment.Status.NO_SHOW).count(),
                "in_progress_count": Appointment.objects.filter(
                    start_at__date=today, status=Appointment.Status.IN_PROGRESS
                ).count(),
                "pending_exams": ExaminationRequest.objects.filter(
                    status=ExaminationRequest.Status.REQUESTED
                ).count(),
                "documents_count": Document.objects.count(),
                "chart_days": [item["day"].strftime("%d/%m") for item in by_day],
                "chart_day_values": [item["total"] for item in by_day],
                "chart_status_labels": [
                    status_labels.get(item["status"], item["status"]) for item in by_status
                ],
                "chart_status_values": [item["total"] for item in by_status],
                "top_professionals": list(top_professionals),
                "top_services": list(top_services),
            }
        )

        from apps.billing.services import clinic_limits

        context["plan_limits"] = clinic_limits(self.request.clinic)
        context["subscription"] = getattr(self.request.clinic, "subscription", None)

        if self.request.clinic.has_module_finance and self.request.user.has_clinic_perm(
            "finance.view", self.request.clinic
        ):
            from apps.finance.models import FinancialTransaction
            from apps.finance.services import dashboard_summary

            context["finance_summary"] = dashboard_summary(self.request.clinic, start, end)
            context["revenue_today"] = dashboard_summary(self.request.clinic, today, today)[
                "period_income"
            ]

            by_method = (
                FinancialTransaction.objects.filter(
                    kind=FinancialTransaction.Kind.INCOME,
                    paid_at__date__gte=start,
                    paid_at__date__lte=end,
                )
                .values("method__name")
                .annotate(total=Count("id"))
                .order_by("-total")
            )
            context["chart_method_labels"] = [
                item["method__name"] or "Nao informado" for item in by_method
            ]
            context["chart_method_values"] = [item["total"] for item in by_method]
        return context


class ProfessionalDashboardView(ClinicViewMixin, TemplateView):
    """Painel do profissional: sua agenda, seus pacientes e suas pendencias."""

    template_name = "dashboard/professional.html"
    required_permission = "appointment.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.examinations.models import ExaminationRequest
        from apps.medical_records.models import MedicalRecordEntry
        from apps.professionals.models import Professional

        professional = Professional.objects.filter(
            user=self.request.user, is_active=True
        ).first()
        context["professional"] = professional
        if professional is None:
            return context

        from apps.scheduling.services import occupancy_for_day

        today = timezone.localdate()
        appointments = Appointment.objects.filter(professional=professional)
        context["occupancy"] = occupancy_for_day(today, [professional])
        context.update(
            {
                "today_appointments": appointments.filter(start_at__date=today)
                .select_related("patient", "service", "room")
                .order_by("start_at"),
                "next_appointments": appointments.filter(
                    start_at__gt=timezone.now(),
                    status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
                )
                .select_related("patient")
                .order_by("start_at")[:8],
                "completed_month": appointments.filter(
                    status=Appointment.Status.COMPLETED,
                    start_at__date__gte=today.replace(day=1),
                ).count(),
                "waiting_now": appointments.filter(
                    start_at__date=today, status=Appointment.Status.CHECKED_IN
                ).count(),
                "drafts": MedicalRecordEntry.objects.filter(
                    professional=professional, is_draft=True
                )
                .select_related("record__patient")
                .order_by("-updated_at")[:10],
                "recent_entries": MedicalRecordEntry.objects.filter(
                    professional=professional, is_draft=False
                )
                .select_related("record__patient")
                .order_by("-attended_at")[:8],
                "pending_exams": ExaminationRequest.objects.filter(
                    professional=professional, status=ExaminationRequest.Status.REQUESTED
                )
                .select_related("patient")
                .order_by("-requested_at")[:8],
                "week_chart_labels": [],
                "week_chart_values": [],
            }
        )

        labels, values = [], []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            labels.append(day.strftime("%d/%m"))
            values.append(appointments.filter(start_at__date=day).count())
        context["week_chart_labels"] = labels
        context["week_chart_values"] = values
        return context


class ReceptionDashboardView(ClinicViewMixin, TemplateView):
    """
    Painel da recepcao: agendamentos do dia, fila de espera e pagamentos --
    sem indicadores clinicos ou financeiros globais (regra: recepcao nao
    acessa o financeiro completo da clinica).
    """

    template_name = "dashboard/reception.html"
    required_permission = "appointment.view"

    #: status que ainda antecedem o atendimento -- usados para calcular o
    #: rotulo "Proximo em N min" / "Atrasado N min" de cada linha da fila.
    _ACTIVE_STATUSES = {
        Appointment.Status.SCHEDULED,
        Appointment.Status.CONFIRMED,
        Appointment.Status.CHECKED_IN,
        Appointment.Status.CALLED,
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.scheduling.services import agenda_summary

        today = timezone.localdate()
        today_appointments = list(
            Appointment.objects.filter(start_at__date=today)
            .select_related("patient", "professional", "service")
            .order_by("start_at")
        )
        now = timezone.now()
        for appointment in today_appointments:
            if appointment.status not in self._ACTIVE_STATUSES:
                appointment.time_label = ""
                continue
            delta_minutes = int((appointment.start_at - now).total_seconds() // 60)
            if delta_minutes > 0:
                appointment.time_label = f"Proximo em {delta_minutes} min"
            elif delta_minutes < 0:
                appointment.time_label = f"Atrasado {abs(delta_minutes)} min"
            else:
                appointment.time_label = "Agora"

        context["today_summary"] = agenda_summary(self.request.clinic, today)
        context["today_appointments"] = today_appointments
        context["waiting_now"] = [
            a for a in today_appointments if a.status == Appointment.Status.CHECKED_IN
        ]
        context["called_now"] = [
            a for a in today_appointments if a.status == Appointment.Status.CALLED
        ]
        context["in_progress_now"] = [
            a for a in today_appointments if a.status == Appointment.Status.IN_PROGRESS
        ]
        context["can_change"] = self.request.user.has_clinic_perm(
            "appointment.change", self.request.clinic
        )

        context["can_manage_payment"] = (
            self.request.clinic.has_module_finance
            and self.request.user.has_clinic_perm("appointment.payment", self.request.clinic)
        )
        if context["can_manage_payment"]:
            from apps.finance.models import FinancialStatus, ReceivableAccount

            today_receivables = ReceivableAccount.objects.filter(service_date=today)
            pending = today_receivables.exclude(
                status__in=[FinancialStatus.PAID, FinancialStatus.CANCELED, FinancialStatus.COURTESY]
            )
            context["payments_received_today"] = sum(
                (r.paid_amount for r in today_receivables), 0
            )
            context["payments_pending_today"] = sum((r.balance for r in pending), 0)
            context["payments_pending_count"] = pending.count()

        # Painel "inteligente": ocupacao do dia + alertas objetivos (nada
        # de "IA" -- so contagens diretas do banco).
        from apps.professionals.models import Professional
        from apps.scheduling.models import WaitingListEntry
        from apps.scheduling.services import occupancy_for_day

        professionals = list(Professional.objects.filter(is_active=True))
        context["occupancy"] = occupancy_for_day(today, professionals)

        alerts = []
        unconfirmed = sum(
            1 for a in today_appointments if a.status == Appointment.Status.SCHEDULED
        )
        if unconfirmed:
            alerts.append(f"{unconfirmed} agendamento(s) de hoje ainda nao confirmado(s).")
        tomorrow_occupancy = occupancy_for_day(today + timedelta(days=1), professionals)
        if tomorrow_occupancy["available"]:
            alerts.append(f"{tomorrow_occupancy['available']} horario(s) livre(s) amanha.")
        waiting_list_count = WaitingListEntry.objects.filter(
            status=WaitingListEntry.Status.WAITING
        ).count()
        if waiting_list_count:
            alerts.append(f"{waiting_list_count} paciente(s) na lista de espera.")
        context["smart_alerts"] = alerts
        return context


class GlobalSearchView(ClinicViewMixin, TemplateView):
    """
    Busca global contextual.

    Retorna apenas registros da clinica ativa e apenas nos dominios em que o
    usuario possui permissao de leitura.
    """

    template_name = "dashboard/search.html"
    required_permission = "clinic.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        term = self.request.GET.get("q", "").strip()
        context["term"] = term
        if len(term) < 2:
            return context

        user = self.request.user
        clinic = self.request.clinic
        results = {}

        if user.has_clinic_perm("patient.view", clinic):
            from apps.patients.models import Patient

            results["Pacientes"] = Patient.objects.filter(
                Q(full_name__icontains=term)
                | Q(social_name__icontains=term)
                | Q(cpf__icontains=term)
            ).order_by("full_name")[:10]

        if user.has_clinic_perm("professional.view", clinic):
            from apps.professionals.models import Professional

            results["Profissionais"] = Professional.objects.filter(
                Q(full_name__icontains=term) | Q(registry_number__icontains=term)
            )[:10]

        if user.has_clinic_perm("appointment.view", clinic):
            appointments = Appointment.objects.filter(
                Q(patient__full_name__icontains=term)
                | Q(professional__full_name__icontains=term)
            ).select_related("patient", "professional")
            if not user.has_clinic_perm("appointment.view_all", clinic):
                appointments = appointments.filter(professional__user=user)
            results["Agendamentos"] = appointments.order_by("-start_at")[:10]

        if user.has_clinic_perm("document.view", clinic):
            from apps.documents.models import Document

            results["Documentos"] = Document.objects.filter(
                Q(title__icontains=term) | Q(patient__full_name__icontains=term)
            ).select_related("patient")[:10]

        context["results"] = results
        context["has_results"] = any(len(value) for value in results.values())
        return context
