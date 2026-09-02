"""Views do painel de staff (recepcao/profissional/administrador)."""
from __future__ import annotations

import io

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, UpdateView

from apps.calling import services
from apps.calling.models import CallPanelConfig, CallTicket
from apps.core.mixins import ClinicViewMixin, RequireModuleMixin
from apps.scheduling.models import Appointment


class CallingModuleMixin(RequireModuleMixin, ClinicViewMixin):
    required_module = "patient_calling"


class TicketRecallView(CallingModuleMixin, View):
    """'Rechamar': reforca o aviso sem mudar o status do agendamento."""

    required_permission = "calling.manage_queue"

    def post(self, request, pk):
        ticket = get_object_or_404(CallTicket.objects.select_related("appointment"), pk=pk)
        if ticket.appointment.status != Appointment.Status.CALLED:
            messages.error(request, "Esta senha nao esta em chamada no momento.")
        else:
            services.recall(ticket, user=request.user)
            messages.success(request, f"Senha {ticket.ticket_number} rechamada.")
        return redirect(request.POST.get("next") or reverse("dashboard:reception"))


class TicketQRView(CallingModuleMixin, View):
    required_permission = "appointment.view"

    def get(self, request, pk):
        try:
            import qrcode
        except ImportError:
            return HttpResponse(status=503)

        ticket = get_object_or_404(CallTicket.objects.all(), pk=pk)
        url = request.build_absolute_uri(
            reverse("calling:patient-ticket", args=[ticket.access_token])
        )
        image = qrcode.make(url)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return HttpResponse(buffer.getvalue(), content_type="image/png")


class PanelTVView(CallingModuleMixin, TemplateView):
    template_name = "calling/panel_tv.html"
    required_permission = "calling.view_panel"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["config"] = services.get_or_create_config(self.request.clinic)
        return context


class PanelStatusApiView(CallingModuleMixin, View):
    required_permission = "calling.view_panel"

    def get(self, request):
        tickets = services.queue_for_clinic(
            request.clinic,
            statuses=[Appointment.Status.CALLED, Appointment.Status.IN_PROGRESS],
        )
        config = services.get_or_create_config(request.clinic)
        data = []
        for ticket in tickets:
            appointment = ticket.appointment
            patient_label = ticket.ticket_number
            if config.display_mode == CallPanelConfig.DisplayMode.INITIALS:
                initials = "".join(p[0] for p in appointment.patient.full_name.split()[:2]).upper()
                patient_label = f"{ticket.ticket_number} - {initials}"
            elif config.display_mode == CallPanelConfig.DisplayMode.FULL_NAME:
                patient_label = f"{ticket.ticket_number} - {appointment.patient.display_name}"
            data.append(
                {
                    "id": str(ticket.pk),
                    "ticket_number": ticket.ticket_number,
                    "label": patient_label,
                    "status": appointment.status,
                    "room": appointment.room.name if appointment.room_id else "",
                    "professional": appointment.professional.display_name,
                    "call_count": ticket.call_count,
                }
            )
        return JsonResponse({"tickets": data, "sound_enabled": config.sound_enabled})


class QueueRecallableView(CallingModuleMixin, View):
    """Fila de senhas ativas do dia -- usado pelo painel de recepcao/profissional."""

    required_permission = "calling.manage_queue"

    def get(self, request):
        tickets = services.queue_for_clinic(
            request.clinic,
            statuses=[
                Appointment.Status.CHECKED_IN,
                Appointment.Status.CALLED,
                Appointment.Status.IN_PROGRESS,
            ],
        )
        data = [
            {
                "id": str(t.pk),
                "appointment_id": str(t.appointment_id),
                "ticket_number": t.ticket_number,
                "priority": t.priority,
                "status": t.appointment.status,
                "call_count": t.call_count,
            }
            for t in tickets
        ]
        return JsonResponse({"tickets": data})


class CallPanelConfigView(CallingModuleMixin, UpdateView):
    model = CallPanelConfig
    form_class = None
    template_name = "calling/config_form.html"
    required_permission = "calling.configure"
    success_url = reverse_lazy("calling:config")

    def get_form_class(self):
        from apps.calling.forms import CallPanelConfigForm

        return CallPanelConfigForm

    def get_object(self, queryset=None):
        return services.get_or_create_config(self.request.clinic)

    def form_valid(self, form):
        messages.success(self.request, "Configuracao da chamada de pacientes salva.")
        return super().form_valid(form)
