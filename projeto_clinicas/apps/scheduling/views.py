"""Views da agenda: visualizacoes, agendamentos, bloqueios e lista de espera."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.core.mixins import ClinicViewMixin
from apps.core.utils import parse_date
from apps.patients.models import Patient
from apps.professionals.models import Professional
from apps.scheduling import services
from apps.scheduling.forms import (
    AppointmentForm,
    CancelAppointmentForm,
    ScheduleBlockForm,
    ScheduleTemplateForm,
    WaitingListForm,
)
from apps.scheduling.models import (
    Appointment,
    ScheduleBlock,
    ScheduleTemplate,
    WaitingListEntry,
)


class AgendaBaseMixin(ClinicViewMixin):
    required_permission = "appointment.view"

    def get_selected_date(self) -> date:
        return parse_date(self.request.GET.get("date", "")) or timezone.localdate()

    def get_professional_queryset(self):
        queryset = Professional.objects.filter(is_active=True).order_by("full_name")
        user = self.request.user
        # Profissional sem permissao de ver a agenda geral so enxerga a propria.
        if not user.has_clinic_perm("appointment.view_all", self.request.clinic):
            queryset = queryset.filter(user=user)
        return queryset

    def get_selected_professional(self):
        professional_id = self.request.GET.get("professional", "")
        queryset = self.get_professional_queryset()
        if professional_id:
            return queryset.filter(pk=professional_id).first()
        return None

    def base_appointments(self):
        queryset = Appointment.objects.select_related(
            "patient", "professional", "service", "room"
        )
        user = self.request.user
        if not user.has_clinic_perm("appointment.view_all", self.request.clinic):
            queryset = queryset.filter(professional__user=user)
        service = self.request.GET.get("service", "")
        if service:
            queryset = queryset.filter(service_id=service)
        room = self.request.GET.get("room", "")
        if room:
            queryset = queryset.filter(room_id=room)
        return queryset

    def get_context_data(self, **kwargs):
        from apps.clinics.models import Room, Service

        context = super().get_context_data(**kwargs)
        context["professionals"] = self.get_professional_queryset()
        context["selected_professional"] = self.get_selected_professional()
        context["selected_date"] = self.get_selected_date()
        context["status_choices"] = Appointment.Status.choices
        context["services"] = Service.objects.filter(is_active=True).order_by("name")
        context["rooms"] = Room.objects.filter(is_active=True).order_by("name")
        return context


class AgendaDayView(AgendaBaseMixin, TemplateView):
    template_name = "scheduling/agenda_day.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        day = context["selected_date"]
        start = timezone.make_aware(
            datetime.combine(day, datetime.min.time()), timezone.get_current_timezone()
        )
        end = start + timedelta(days=1)

        appointments = self.base_appointments().filter(start_at__gte=start, start_at__lt=end)
        professional = context["selected_professional"]
        if professional:
            appointments = appointments.filter(professional=professional)

        context["appointments"] = appointments.order_by("start_at")
        context["summary"] = services.agenda_summary(self.request.clinic, day)
        context["previous_day"] = day - timedelta(days=1)
        context["next_day"] = day + timedelta(days=1)
        if professional:
            context["slots"] = services.day_slots(professional, day)
        return context


class AgendaWeekView(AgendaBaseMixin, TemplateView):
    template_name = "scheduling/agenda_week.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        day = context["selected_date"]
        week_start = day - timedelta(days=day.weekday())
        week_end = week_start + timedelta(days=7)
        start = timezone.make_aware(
            datetime.combine(week_start, datetime.min.time()), timezone.get_current_timezone()
        )
        end = start + timedelta(days=7)

        appointments = self.base_appointments().filter(start_at__gte=start, start_at__lt=end)
        professional = context["selected_professional"]
        if professional:
            appointments = appointments.filter(professional=professional)

        days = []
        for offset in range(7):
            current = week_start + timedelta(days=offset)
            days.append(
                {
                    "date": current,
                    "appointments": [
                        item
                        for item in appointments
                        if timezone.localtime(item.start_at).date() == current
                    ],
                }
            )
        context["week_days"] = days
        context["week_start"] = week_start
        context["week_end"] = week_end - timedelta(days=1)
        context["previous_week"] = week_start - timedelta(days=7)
        context["next_week"] = week_start + timedelta(days=7)
        return context


class AgendaMonthView(AgendaBaseMixin, TemplateView):
    template_name = "scheduling/agenda_month.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        day = context["selected_date"]
        first_day = day.replace(day=1)
        _, days_in_month = calendar.monthrange(day.year, day.month)
        last_day = first_day + timedelta(days=days_in_month)

        start = timezone.make_aware(
            datetime.combine(first_day, datetime.min.time()), timezone.get_current_timezone()
        )
        end = timezone.make_aware(
            datetime.combine(last_day, datetime.min.time()), timezone.get_current_timezone()
        )
        appointments = self.base_appointments().filter(start_at__gte=start, start_at__lt=end)
        professional = context["selected_professional"]
        if professional:
            appointments = appointments.filter(professional=professional)

        counters = {}
        for item in appointments:
            key = timezone.localtime(item.start_at).date()
            counters.setdefault(key, []).append(item)

        weeks = []
        calendar.setfirstweekday(calendar.MONDAY)
        for week in calendar.monthcalendar(day.year, day.month):
            row = []
            for day_number in week:
                current = date(day.year, day.month, day_number) if day_number else None
                row.append(
                    {
                        "date": current,
                        "appointments": counters.get(current, []) if current else [],
                    }
                )
            weeks.append(row)
        context["weeks"] = weeks
        context["month_label"] = f"{first_day:%m/%Y}"
        context["previous_month"] = (first_day - timedelta(days=1)).replace(day=1)
        context["next_month"] = last_day
        return context


class AgendaListView(AgendaBaseMixin, ListView):
    template_name = "scheduling/agenda_list.html"
    context_object_name = "appointments"
    paginate_by = 30

    def get_queryset(self):
        queryset = self.base_appointments()
        start = parse_date(self.request.GET.get("start", ""))
        end = parse_date(self.request.GET.get("end", ""))
        if start:
            queryset = queryset.filter(start_at__date__gte=start)
        if end:
            queryset = queryset.filter(start_at__date__lte=end)
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        professional = self.request.GET.get("professional", "")
        if professional:
            queryset = queryset.filter(professional_id=professional)
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(patient__full_name__icontains=search)
                | Q(patient__social_name__icontains=search)
            )
        return queryset.order_by("-start_at")


class AppointmentDetailView(ClinicViewMixin, DetailView):
    model = Appointment
    template_name = "scheduling/appointment_detail.html"
    context_object_name = "appointment"
    required_permission = "appointment.view"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "patient", "professional__user", "service", "room", "insurance"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_form"] = CancelAppointmentForm()
        context["can_change"] = self.request.user.has_clinic_perm(
            "appointment.change", self.request.clinic
        )
        context["can_manage_payment"] = (
            self.request.clinic.has_module_finance
            and self.request.user.has_clinic_perm("appointment.payment", self.request.clinic)
        )
        if self.request.clinic.has_module_finance:
            from apps.finance.models import PaymentMethod, ReceivableAccount

            context["receivable"] = (
                ReceivableAccount.objects.filter(appointment=self.object)
                .select_related("expected_payment_method")
                .prefetch_related("transactions__method", "transactions__created_by")
                .first()
            )
            if context["can_manage_payment"]:
                context["payment_methods"] = PaymentMethod.objects.filter(is_active=True)

        from apps.audit.models import AuditLog

        context["history"] = (
            AuditLog.objects.filter(
                clinic=self.request.clinic,
                object_type="scheduling.Appointment",
                object_id=str(self.object.pk),
            )
            .select_related("user")
            .order_by("created_at")
        )
        return context


class AppointmentCreateView(ClinicViewMixin, CreateView):
    model = Appointment
    form_class = AppointmentForm
    template_name = "scheduling/appointment_form.html"
    required_permission = "appointment.add"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        selected = parse_date(self.request.GET.get("date", ""))
        if selected:
            initial["date"] = selected
        if self.request.GET.get("time"):
            initial["time"] = self.request.GET["time"]
        if self.request.GET.get("professional"):
            initial["professional"] = self.request.GET["professional"]
        if self.request.GET.get("patient"):
            initial["patient"] = self.request.GET["patient"]
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # O <select> de paciente/profissional virou um campo de busca (ver
        # AppointmentForm.Meta.widgets) -- quando a tela chega com um id
        # pre-selecionado via querystring (ex.: busca rapida da recepcao,
        # "Novo agendamento" a partir do perfil do paciente), o campo de
        # texto tambem precisa vir preenchido com o nome, nao so o id.
        patient_id = self.request.GET.get("patient")
        if patient_id:
            context["prefill_patient"] = Patient.objects.filter(pk=patient_id).first()
        professional_id = self.request.GET.get("professional")
        if professional_id:
            context["prefill_professional"] = Professional.objects.filter(
                pk=professional_id
            ).first()
        return context

    def form_valid(self, form):
        try:
            appointment = services.create_appointment(
                clinic=self.request.clinic,
                patient=form.cleaned_data["patient"],
                professional=form.cleaned_data["professional"],
                start_at=form.cleaned_data["start_at"],
                service=form.cleaned_data.get("service"),
                room=form.cleaned_data.get("room"),
                insurance=form.cleaned_data.get("insurance"),
                duration_minutes=form.cleaned_data.get("duration_minutes"),
                notes=form.cleaned_data.get("notes", ""),
                created_by=self.request.user,
                is_overbooking=form.cleaned_data.get("is_overbooking", False),
                gross_amount=form.cleaned_data.get("gross_amount"),
                discount=form.cleaned_data.get("discount"),
                addition=form.cleaned_data.get("addition"),
                payment_method=form.cleaned_data.get("payment_method"),
                pay_now=form.cleaned_data.get("pay_now", False),
                amount_paid_now=form.cleaned_data.get("amount_paid_now"),
                is_courtesy=form.cleaned_data.get("is_courtesy", False),
            )
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        self.object = appointment
        messages.success(self.request, "Agendamento criado com sucesso.")
        return redirect("scheduling:appointment-detail", pk=appointment.pk)


class AppointmentUpdateView(ClinicViewMixin, UpdateView):
    model = Appointment
    form_class = AppointmentForm
    template_name = "scheduling/appointment_form.html"
    required_permission = "appointment.change"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        appointment = form.save(commit=False)
        appointment.start_at = form.cleaned_data["start_at"]
        appointment.end_at = form.cleaned_data["end_at"]
        try:
            services.validate_appointment(appointment, allow_overbooking=True)
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        appointment.save()
        self.object = appointment
        messages.success(self.request, "Agendamento atualizado.")
        return redirect("scheduling:appointment-detail", pk=appointment.pk)


class AppointmentStatusView(ClinicViewMixin, View):
    """Confirma, registra chegada, inicia, conclui, cancela ou marca falta."""

    required_permission = "appointment.change"

    def post(self, request, pk, status):
        appointment = get_object_or_404(Appointment.objects.all(), pk=pk)
        if status == Appointment.Status.CANCELED and not request.user.has_clinic_perm(
            "appointment.cancel", request.clinic
        ):
            messages.error(request, "Voce nao tem permissao para cancelar agendamentos.")
            return redirect("scheduling:appointment-detail", pk=pk)
        extra = {}
        if status == Appointment.Status.CANCELED:
            disposition = request.POST.get("payment_disposition", "")
            extra["payment_disposition"] = (
                "refund" if disposition in CancelAppointmentForm.REFUND_DISPOSITIONS else ""
            )
        try:
            services.change_status(
                appointment,
                status,
                user=request.user,
                reason=request.POST.get("reason", ""),
                **extra,
            )
            messages.success(request, "Status atualizado.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect(request.POST.get("next") or reverse(
            "scheduling:appointment-detail", args=[pk]
        ))


class AppointmentRescheduleView(ClinicViewMixin, View):
    required_permission = "appointment.change"

    def post(self, request, pk):
        appointment = get_object_or_404(Appointment.objects.all(), pk=pk)
        new_date = parse_date(request.POST.get("date", ""))
        new_time = request.POST.get("time", "")
        if not new_date or not new_time:
            messages.error(request, "Informe a nova data e horario.")
            return redirect("scheduling:appointment-detail", pk=pk)
        try:
            hour, minute = (int(part) for part in new_time.split(":")[:2])
            new_start = timezone.make_aware(
                datetime.combine(new_date, datetime.min.time().replace(hour=hour, minute=minute)),
                timezone.get_current_timezone(),
            )
            services.reschedule(appointment, new_start, user=request.user)
            messages.success(request, "Agendamento remarcado.")
        except (ValueError, ValidationError) as exc:
            messages.error(request, getattr(exc, "messages", [str(exc)])[0])
        return redirect("scheduling:appointment-detail", pk=pk)


class SlotsApiView(ClinicViewMixin, View):
    """Horarios livres de um profissional (usado pelo formulario via JS)."""

    required_permission = "appointment.view"

    def get(self, request):
        professional = get_object_or_404(
            Professional.objects.filter(is_active=True), pk=request.GET.get("professional")
        )
        day = parse_date(request.GET.get("date", "")) or timezone.localdate()
        service = None
        service_id = request.GET.get("service")
        if service_id:
            from apps.clinics.models import Service

            service = Service.objects.filter(pk=service_id).first()
        slots = services.day_slots(professional, day, service)
        return JsonResponse(
            {
                "date": day.isoformat(),
                "slots": [
                    {
                        "start": timezone.localtime(slot.start).strftime("%H:%M"),
                        "end": timezone.localtime(slot.end).strftime("%H:%M"),
                        "available": slot.available,
                        "reason": slot.reason,
                    }
                    for slot in slots
                ],
            }
        )


# ---------------------------------------------------------------------------
# Disponibilidade e bloqueios
# ---------------------------------------------------------------------------
class ScheduleTemplateListView(ClinicViewMixin, ListView):
    model = ScheduleTemplate
    template_name = "scheduling/schedule_list.html"
    context_object_name = "templates"
    required_permission = "schedule.manage"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("professional", "room")
        user = self.request.user
        if not user.has_clinic_perm("professional.change", self.request.clinic):
            queryset = queryset.filter(professional__user=user)
        professional = self.request.GET.get("professional", "")
        if professional:
            queryset = queryset.filter(professional_id=professional)
        return queryset.order_by("professional__full_name", "weekday", "start_time")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["professionals"] = Professional.objects.filter(is_active=True)
        context["blocks"] = ScheduleBlock.objects.filter(
            end_at__gte=timezone.now()
        ).select_related("professional")[:20]
        return context


class ScheduleTemplateCreateView(ClinicViewMixin, CreateView):
    model = ScheduleTemplate
    form_class = ScheduleTemplateForm
    template_name = "scheduling/schedule_form.html"
    required_permission = "schedule.manage"
    success_url = reverse_lazy("scheduling:schedule-list")

    def form_valid(self, form):
        messages.success(self.request, "Disponibilidade cadastrada.")
        return super().form_valid(form)


class ScheduleTemplateUpdateView(ClinicViewMixin, UpdateView):
    model = ScheduleTemplate
    form_class = ScheduleTemplateForm
    template_name = "scheduling/schedule_form.html"
    required_permission = "schedule.manage"
    success_url = reverse_lazy("scheduling:schedule-list")


class ScheduleTemplateDeleteView(ClinicViewMixin, View):
    required_permission = "schedule.manage"

    def post(self, request, pk):
        template = get_object_or_404(ScheduleTemplate.objects.all(), pk=pk)
        template.delete(user=request.user)
        messages.success(request, "Disponibilidade removida.")
        return redirect("scheduling:schedule-list")


class ScheduleBlockCreateView(ClinicViewMixin, CreateView):
    model = ScheduleBlock
    form_class = ScheduleBlockForm
    template_name = "scheduling/block_form.html"
    required_permission = "schedule.manage"
    success_url = reverse_lazy("scheduling:schedule-list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Bloqueio registrado.")
        return super().form_valid(form)


class ScheduleBlockDeleteView(ClinicViewMixin, View):
    required_permission = "schedule.manage"

    def post(self, request, pk):
        block = get_object_or_404(ScheduleBlock.objects.all(), pk=pk)
        block.delete(user=request.user)
        messages.success(request, "Bloqueio removido.")
        return redirect("scheduling:schedule-list")


# ---------------------------------------------------------------------------
# Lista de espera
# ---------------------------------------------------------------------------
class WaitingListView(ClinicViewMixin, ListView):
    model = WaitingListEntry
    template_name = "scheduling/waiting_list.html"
    context_object_name = "entries"
    required_permission = "appointment.view"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(status__in=[WaitingListEntry.Status.WAITING, WaitingListEntry.Status.CONTACTED])
            .select_related("patient", "professional", "service")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = WaitingListForm()
        return context


class WaitingListCreateView(ClinicViewMixin, CreateView):
    model = WaitingListEntry
    form_class = WaitingListForm
    template_name = "scheduling/waiting_list.html"
    required_permission = "appointment.add"
    success_url = reverse_lazy("scheduling:waiting-list")

    def form_valid(self, form):
        messages.success(self.request, "Paciente incluido na lista de espera.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Nao foi possivel incluir na lista de espera.")
        return redirect("scheduling:waiting-list")


class WaitingListUpdateStatusView(ClinicViewMixin, View):
    required_permission = "appointment.change"

    def post(self, request, pk, status):
        entry = get_object_or_404(WaitingListEntry.objects.all(), pk=pk)
        if status not in WaitingListEntry.Status.values:
            messages.error(request, "Status invalido.")
            return redirect("scheduling:waiting-list")
        entry.status = status
        if status == WaitingListEntry.Status.CONTACTED:
            entry.contacted_at = timezone.now()
        entry.save()
        messages.success(request, "Lista de espera atualizada.")
        return redirect("scheduling:waiting-list")
