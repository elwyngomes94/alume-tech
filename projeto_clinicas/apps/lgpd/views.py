"""Painel LGPD da clinica."""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.accounts.forms import BootstrapFormMixin
from apps.core.mixins import ClinicViewMixin
from apps.lgpd import services
from apps.lgpd.models import (
    Consent,
    ConsentType,
    DataSubjectRequest,
    SecurityIncident,
)
from apps.patients.models import Patient


class ConsentTypeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ConsentType
        fields = ["name", "description", "content", "legal_basis", "is_required", "version",
                  "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "content": forms.Textarea(attrs={"rows": 10}),
        }


class ConsentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Consent
        fields = ["patient", "consent_type", "granted", "channel"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.all()
        self.fields["consent_type"].queryset = ConsentType.objects.filter(is_active=True)


class DataSubjectRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DataSubjectRequest
        fields = ["patient", "requester_name", "requester_email", "kind", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.all()
        self.fields["patient"].required = False


class IncidentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SecurityIncident
        fields = [
            "title",
            "description",
            "severity",
            "status",
            "detected_at",
            "affected_records",
            "contains_sensitive_data",
            "measures_taken",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "measures_taken": forms.Textarea(attrs={"rows": 3}),
            "detected_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["detected_at"].input_formats = ["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"]


class LgpdDashboardView(ClinicViewMixin, TemplateView):
    template_name = "lgpd/dashboard.html"
    required_permission = "lgpd.manage"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["requests"] = DataSubjectRequest.objects.select_related("patient")[:10]
        context["pending_requests"] = DataSubjectRequest.objects.filter(
            status__in=[DataSubjectRequest.Status.RECEIVED, DataSubjectRequest.Status.IN_PROGRESS]
        ).count()
        context["consent_types"] = ConsentType.objects.filter(is_active=True)
        context["consents_total"] = Consent.objects.count()
        context["incidents"] = SecurityIncident.objects.all()[:5]
        context["retention"] = services.retention_report(self.request.clinic)
        return context


class ConsentTypeListView(ClinicViewMixin, ListView):
    model = ConsentType
    template_name = "lgpd/consent_type_list.html"
    context_object_name = "consent_types"
    required_permission = "lgpd.manage"


class ConsentTypeCreateView(ClinicViewMixin, CreateView):
    model = ConsentType
    form_class = ConsentTypeForm
    template_name = "lgpd/consent_type_form.html"
    required_permission = "lgpd.manage"
    success_url = reverse_lazy("lgpd:consent-type-list")


class ConsentTypeUpdateView(ClinicViewMixin, UpdateView):
    model = ConsentType
    form_class = ConsentTypeForm
    template_name = "lgpd/consent_type_form.html"
    required_permission = "lgpd.manage"
    success_url = reverse_lazy("lgpd:consent-type-list")


class ConsentListView(ClinicViewMixin, ListView):
    model = Consent
    template_name = "lgpd/consent_list.html"
    context_object_name = "consents"
    paginate_by = 30
    required_permission = "lgpd.manage"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("patient", "consent_type")
        patient = self.request.GET.get("patient")
        if patient:
            queryset = queryset.filter(patient_id=patient)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = ConsentForm()
        return context


class ConsentCreateView(ClinicViewMixin, CreateView):
    model = Consent
    form_class = ConsentForm
    template_name = "lgpd/consent_list.html"
    required_permission = "lgpd.manage"
    success_url = reverse_lazy("lgpd:consent-list")

    def form_valid(self, form):
        from apps.core.middleware import client_ip

        consent = form.save(commit=False)
        consent.clinic = self.request.clinic
        consent.collected_by = self.request.user
        consent.ip_address = client_ip(self.request)
        consent.save()
        self.object = consent
        messages.success(self.request, "Consentimento registrado.")
        return redirect(self.success_url)

    def form_invalid(self, form):
        messages.error(self.request, "Nao foi possivel registrar o consentimento.")
        return redirect(self.success_url)


class ConsentRevokeView(ClinicViewMixin, View):
    required_permission = "lgpd.manage"

    def post(self, request, pk):
        consent = get_object_or_404(Consent.objects.all(), pk=pk)
        consent.revoke(request.POST.get("reason", ""))
        messages.success(request, "Consentimento revogado.")
        return redirect("lgpd:consent-list")


class DataRequestListView(ClinicViewMixin, ListView):
    model = DataSubjectRequest
    template_name = "lgpd/request_list.html"
    context_object_name = "requests"
    paginate_by = 25
    required_permission = "lgpd.manage"

    def get_queryset(self):
        return super().get_queryset().select_related("patient")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = DataSubjectRequestForm()
        return context


class DataRequestCreateView(ClinicViewMixin, CreateView):
    model = DataSubjectRequest
    form_class = DataSubjectRequestForm
    template_name = "lgpd/request_list.html"
    required_permission = "lgpd.manage"
    success_url = reverse_lazy("lgpd:request-list")

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.clinic = self.request.clinic
        obj.save()
        self.object = obj
        messages.success(self.request, "Solicitacao registrada. Prazo legal: 15 dias.")
        return redirect(self.success_url)

    def form_invalid(self, form):
        messages.error(self.request, "Dados invalidos para a solicitacao.")
        return redirect(self.success_url)


class DataRequestDetailView(ClinicViewMixin, DetailView):
    model = DataSubjectRequest
    template_name = "lgpd/request_detail.html"
    context_object_name = "request_obj"
    required_permission = "lgpd.manage"


class DataRequestResolveView(ClinicViewMixin, View):
    required_permission = "lgpd.manage"

    def post(self, request, pk):
        obj = get_object_or_404(DataSubjectRequest.objects.all(), pk=pk)
        status = request.POST.get("status", DataSubjectRequest.Status.COMPLETED)
        if status in DataSubjectRequest.Status.values:
            obj.status = status
            obj.response = request.POST.get("response", "")
            obj.handled_by = request.user
            if status == DataSubjectRequest.Status.COMPLETED:
                obj.completed_at = timezone.now()
            obj.save()
            messages.success(request, "Solicitacao atualizada.")
        return redirect("lgpd:request-detail", pk=pk)


class PatientAnonymizeView(ClinicViewMixin, View):
    required_permission = "lgpd.manage"

    def post(self, request, pk):
        patient = get_object_or_404(Patient.objects.all(), pk=pk)
        services.anonymize_patient(
            patient, user=request.user, reason=request.POST.get("reason", "")
        )
        messages.success(
            request,
            "Cadastro anonimizado. O historico assistencial foi preservado sem "
            "identificacao do titular.",
        )
        return redirect("patients:list")


class IncidentListView(ClinicViewMixin, ListView):
    model = SecurityIncident
    template_name = "lgpd/incident_list.html"
    context_object_name = "incidents"
    required_permission = "lgpd.manage"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = IncidentForm()
        return context


class IncidentCreateView(ClinicViewMixin, CreateView):
    model = SecurityIncident
    form_class = IncidentForm
    template_name = "lgpd/incident_form.html"
    required_permission = "lgpd.manage"
    success_url = reverse_lazy("lgpd:incident-list")

    def form_valid(self, form):
        form.instance.reported_by = self.request.user
        messages.success(self.request, "Incidente registrado.")
        return super().form_valid(form)
