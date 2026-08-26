"""
Portal do paciente.

Todo acesso parte do cadastro vinculado ao usuario autenticado
(``Patient.portal_user``). Nenhuma view aceita um id de paciente vindo da URL:
o paciente e sempre resolvido a partir da sessao, o que torna impossivel
consultar dados de outro titular alterando a URL.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView, UpdateView

from apps.audit.models import AuditAction
from apps.audit.services import log_action
from apps.core.middleware import client_ip
from apps.core.mixins import PatientRequiredMixin
from apps.core.tenancy import tenant_context
from apps.core.utils import parse_date
from apps.documents.models import Document
from apps.documents.services import register_access
from apps.examinations.models import ExaminationRequest
from apps.medical_records.models import Prescription
from apps.patients.forms import PatientSelfUpdateForm
from apps.patients.models import Patient
from apps.scheduling.models import Appointment


class PortalBaseMixin(PatientRequiredMixin):
    """Resolve o cadastro do paciente e ativa o tenant correspondente."""

    def dispatch(self, request, *args, **kwargs):
        self.patient = None
        if request.user.is_authenticated:
            self.patient = (
                Patient.all_objects.filter(portal_user=request.user, is_deleted=False)
                .select_related("clinic")
                .first()
            )
            if self.patient is None and not request.path.endswith("/sem-cadastro/"):
                return redirect("portal:no-record")
            if self.patient is not None:
                self._tenant = tenant_context(self.patient.clinic)
                self._tenant.__enter__()
                request.clinic = self.patient.clinic
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            if getattr(self, "_tenant", None) is not None:
                self._tenant.__exit__(None, None, None)
                self._tenant = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["patient"] = self.patient
        context["clinic"] = self.patient.clinic if self.patient else None
        return context


class PortalHomeView(PortalBaseMixin, TemplateView):
    template_name = "portal/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.patient
        context.update(
            {
                "next_appointments": Appointment.objects.filter(
                    patient=patient,
                    start_at__gte=timezone.now(),
                    status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
                )
                .select_related("professional", "service")
                .order_by("start_at")[:5],
                "past_appointments": Appointment.objects.filter(
                    patient=patient, start_at__lt=timezone.now()
                )
                .select_related("professional")
                .order_by("-start_at")[:5],
                "documents": Document.objects.filter(
                    patient=patient, visible_to_patient=True
                ).order_by("-created_at")[:5],
                "exams": ExaminationRequest.objects.filter(
                    patient=patient, released_to_patient=True
                ).order_by("-requested_at")[:5],
            }
        )
        return context


class PortalNoRecordView(PatientRequiredMixin, TemplateView):
    template_name = "portal/no_record.html"


class PortalProfileView(PortalBaseMixin, UpdateView):
    form_class = PatientSelfUpdateForm
    template_name = "portal/profile.html"
    success_url = reverse_lazy("portal:profile")

    def get_object(self, queryset=None):
        return self.patient

    def form_valid(self, form):
        messages.success(self.request, "Dados atualizados.")
        log_action(
            AuditAction.UPDATE,
            obj=self.patient,
            description="Paciente atualizou os proprios dados pelo portal",
            request=self.request,
        )
        return super().form_valid(form)


class PortalAppointmentListView(PortalBaseMixin, ListView):
    template_name = "portal/appointments.html"
    context_object_name = "appointments"
    paginate_by = 20

    def get_queryset(self):
        return (
            Appointment.objects.filter(patient=self.patient)
            .select_related("professional", "service", "room")
            .order_by("-start_at")
        )


class PortalAppointmentRequestForm(forms.Form):
    """Solicitacao de agendamento feita pelo proprio paciente."""

    professional = forms.ModelChoiceField(label="Profissional", queryset=None)
    service = forms.ModelChoiceField(label="Servico", queryset=None, required=False)
    date = forms.DateField(label="Data desejada", widget=forms.DateInput(attrs={"type": "date"}))
    time = forms.TimeField(label="Horario", widget=forms.TimeInput(attrs={"type": "time"}))
    notes = forms.CharField(label="Observacoes", required=False,
                            widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.clinics.models import Service
        from apps.professionals.models import Professional

        self.fields["professional"].queryset = Professional.objects.filter(
            is_active=True, accepts_online_scheduling=True
        )
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class PortalAppointmentRequestView(PortalBaseMixin, View):
    template_name = "portal/appointment_request.html"

    def _check_enabled(self):
        settings_obj = getattr(self.patient.clinic, "settings", None)
        if settings_obj is not None and not settings_obj.allow_patient_scheduling:
            raise PermissionDenied(
                "Esta clinica nao habilitou a solicitacao de agendamento pelo portal."
            )

    def get(self, request):
        self._check_enabled()
        return render(request, self.template_name, {
            "form": PortalAppointmentRequestForm(),
            "patient": self.patient,
            "clinic": self.patient.clinic,
        })

    def post(self, request):
        self._check_enabled()
        form = PortalAppointmentRequestForm(request.POST)
        if form.is_valid():
            from apps.scheduling import services as scheduling_services

            start = timezone.make_aware(
                datetime.combine(form.cleaned_data["date"], form.cleaned_data["time"]),
                timezone.get_current_timezone(),
            )
            try:
                appointment = scheduling_services.create_appointment(
                    clinic=self.patient.clinic,
                    patient=self.patient,
                    professional=form.cleaned_data["professional"],
                    service=form.cleaned_data.get("service"),
                    start_at=start,
                    notes=form.cleaned_data.get("notes", ""),
                    origin=Appointment.Origin.PORTAL,
                    created_by=request.user,
                )
                messages.success(
                    request,
                    "Solicitacao enviada. A clinica confirmara o seu agendamento em breve.",
                )
                return redirect("portal:appointments")
            except ValidationError as exc:
                for message in exc.messages:
                    form.add_error(None, message)
        return render(request, self.template_name, {
            "form": form,
            "patient": self.patient,
            "clinic": self.patient.clinic,
        })


class PortalAppointmentCancelView(PortalBaseMixin, View):
    def post(self, request, pk):
        appointment = get_object_or_404(
            Appointment.objects.filter(patient=self.patient), pk=pk
        )
        settings_obj = getattr(self.patient.clinic, "settings", None)
        min_hours = settings_obj.patient_cancel_hours if settings_obj else 24
        if appointment.start_at - timezone.now() < timedelta(hours=min_hours):
            messages.error(
                request,
                f"O cancelamento pelo portal exige {min_hours}h de antecedencia. "
                "Entre em contato com a clinica.",
            )
            return redirect("portal:appointments")

        from apps.scheduling import services as scheduling_services

        try:
            scheduling_services.change_status(
                appointment,
                Appointment.Status.CANCELED,
                user=request.user,
                reason="Cancelado pelo paciente no portal",
            )
            messages.success(request, "Agendamento cancelado.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("portal:appointments")


class PortalDocumentListView(PortalBaseMixin, ListView):
    template_name = "portal/documents.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self):
        return (
            Document.objects.filter(patient=self.patient, visible_to_patient=True)
            .select_related("category")
            .order_by("-created_at")
        )


class PortalDocumentDownloadView(PortalBaseMixin, View):
    """Download restrito aos proprios documentos liberados."""

    def get(self, request, pk):
        document = get_object_or_404(
            Document.objects.filter(patient=self.patient, visible_to_patient=True), pk=pk
        )
        try:
            handle = document.file.open("rb")
        except FileNotFoundError as exc:  # pragma: no cover
            raise Http404("Arquivo indisponivel.") from exc
        register_access(document, request.user, client_ip(request), "download")
        log_action(
            AuditAction.DOWNLOAD,
            obj=document,
            description="Download pelo portal do paciente",
            request=request,
            is_sensitive=True,
        )
        response = FileResponse(
            handle, content_type=document.content_type or "application/octet-stream"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{document.original_name or "documento"}"'
        )
        response["Cache-Control"] = "no-store, private"
        return response


class PortalExaminationListView(PortalBaseMixin, ListView):
    template_name = "portal/examinations.html"
    context_object_name = "requests"
    paginate_by = 20

    def get_queryset(self):
        return (
            ExaminationRequest.objects.filter(patient=self.patient, released_to_patient=True)
            .prefetch_related("items", "results__document")
            .order_by("-requested_at")
        )


class PortalPrescriptionListView(PortalBaseMixin, ListView):
    template_name = "portal/prescriptions.html"
    context_object_name = "prescriptions"
    paginate_by = 20

    def get_queryset(self):
        return (
            Prescription.objects.filter(patient=self.patient, released_to_patient=True)
            .select_related("professional")
            .order_by("-issued_at")
        )


class PortalPrescriptionDetailView(PortalBaseMixin, DetailView):
    template_name = "portal/prescription_detail.html"
    context_object_name = "prescription"

    def get_queryset(self):
        return Prescription.objects.filter(patient=self.patient, released_to_patient=True)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        log_action(
            AuditAction.VIEW_SENSITIVE,
            obj=obj,
            description="Paciente consultou a propria prescricao",
            request=self.request,
            is_sensitive=True,
        )
        return obj


class PortalHistoryView(PortalBaseMixin, TemplateView):
    """Historico permitido: atendimentos realizados, sem conteudo clinico bruto."""

    template_name = "portal/history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["appointments"] = (
            Appointment.objects.filter(
                patient=self.patient, status=Appointment.Status.COMPLETED
            )
            .select_related("professional", "service")
            .order_by("-start_at")[:50]
        )
        return context


class PortalDataExportView(PortalBaseMixin, View):
    """Exportacao dos proprios dados (LGPD art. 18, IV e V)."""

    def get(self, request):
        from django.http import JsonResponse

        from apps.lgpd.services import build_patient_export

        payload = build_patient_export(self.patient)
        log_action(
            AuditAction.EXPORT,
            obj=self.patient,
            description="Paciente exportou os proprios dados (LGPD)",
            request=request,
            is_sensitive=True,
        )
        response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
        response["Content-Disposition"] = 'attachment; filename="meus-dados.json"'
        return response
