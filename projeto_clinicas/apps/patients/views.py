"""Views de pacientes (painel da clinica)."""
from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.audit.models import AuditAction
from apps.audit.services import log_action
from apps.core.mixins import ClinicViewMixin
from apps.core.utils import parse_date
from apps.patients.forms import (
    PatientAddressFormSet,
    PatientContactFormSet,
    PatientForm,
)
from apps.patients.models import Patient


class PatientListView(ClinicViewMixin, ListView):
    model = Patient
    template_name = "patients/patient_list.html"
    context_object_name = "patients"
    paginate_by = 25
    required_permission = "patient.view"

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("insurance")
            .order_by("full_name")
        )
        search = self.request.GET.get("q", "").strip()
        if search:
            condition = (
                Q(full_name__icontains=search)
                | Q(social_name__icontains=search)
                | Q(cpf__icontains=search)
                | Q(email__icontains=search)
                | Q(mobile__icontains=search)
            )
            if search.isdigit():
                condition |= Q(record_number=int(search))
            queryset = queryset.filter(condition)
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        insurance = self.request.GET.get("insurance", "")
        if insurance:
            queryset = queryset.filter(insurance_id=insurance)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.clinics.models import InsurancePlan

        context["status_choices"] = Patient.Status.choices
        context["insurances"] = InsurancePlan.objects.filter(is_active=True)
        context["total"] = context["paginator"].count if context.get("paginator") else 0
        return context


class PatientDetailView(ClinicViewMixin, DetailView):
    model = Patient
    template_name = "patients/patient_detail.html"
    context_object_name = "patient"
    required_permission = "patient.view"
    audit_object_access = True
    audit_description = "Consulta ao cadastro do paciente"

    def get_queryset(self):
        return super().get_queryset().select_related("insurance", "portal_user")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.object
        user = self.request.user

        from apps.documents.models import Document
        from apps.examinations.models import ExaminationRequest
        from apps.medical_records.models import MedicalRecordEntry
        from apps.scheduling.models import Appointment

        context["appointments"] = (
            Appointment.objects.filter(patient=patient)
            .select_related("professional__user", "service")
            .order_by("-start_at")[:15]
        )
        context["can_view_records"] = user.has_clinic_perm(
            "medicalrecord.view", self.request.clinic
        )
        if context["can_view_records"]:
            context["record_entries"] = (
                MedicalRecordEntry.objects.filter(record__patient=patient, is_draft=False)
                .select_related("professional__user", "template")
                .order_by("-created_at")[:10]
            )
        context["documents"] = (
            Document.objects.filter(patient=patient)
            .select_related("category")
            .order_by("-created_at")[:15]
            if user.has_clinic_perm("document.view", self.request.clinic)
            else []
        )
        context["examinations"] = (
            ExaminationRequest.objects.filter(patient=patient)
            .select_related("professional__user")
            .order_by("-created_at")[:10]
            if user.has_clinic_perm("examination.view", self.request.clinic)
            else []
        )
        context["addresses"] = patient.addresses.all()
        context["contacts"] = patient.contacts.all()
        return context


class PatientFormMixin:
    """Trata paciente + enderecos + contatos em um unico formulario."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context["address_formset"] = PatientAddressFormSet(
                self.request.POST, instance=self.object
            )
            context["contact_formset"] = PatientContactFormSet(
                self.request.POST, instance=self.object
            )
        else:
            context["address_formset"] = PatientAddressFormSet(instance=self.object)
            context["contact_formset"] = PatientContactFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        address_formset = context["address_formset"]
        contact_formset = context["contact_formset"]
        response = super().form_valid(form)
        for formset in (address_formset, contact_formset):
            formset.instance = self.object
            if formset.is_valid():
                formset.save()
        messages.success(self.request, "Cadastro do paciente salvo com sucesso.")
        return response


class PatientCreateView(PatientFormMixin, ClinicViewMixin, CreateView):
    model = Patient
    form_class = PatientForm
    template_name = "patients/patient_form.html"
    required_permission = "patient.add"

    def get_success_url(self):
        return reverse("patients:detail", args=[self.object.pk])


class PatientUpdateView(PatientFormMixin, ClinicViewMixin, UpdateView):
    model = Patient
    form_class = PatientForm
    template_name = "patients/patient_form.html"
    required_permission = "patient.change"

    def get_success_url(self):
        return reverse("patients:detail", args=[self.object.pk])


class PatientDeleteView(ClinicViewMixin, View):
    """Exclusao logica: o historico clinico e preservado por retencao legal."""

    required_permission = "patient.delete"

    def post(self, request, pk):
        patient = get_object_or_404(Patient.objects.all(), pk=pk)
        patient.delete(user=request.user)
        messages.success(request, "Paciente arquivado (exclusao logica).")
        return redirect("patients:list")


class PatientSearchView(ClinicViewMixin, View):
    """Autocomplete de pacientes usado na agenda e no prontuario."""

    required_permission = "patient.view"

    def get(self, request):
        term = request.GET.get("q", "").strip()
        results = []
        if len(term) >= 2:
            queryset = Patient.objects.filter(
                Q(full_name__icontains=term)
                | Q(social_name__icontains=term)
                | Q(cpf__icontains=term)
            ).order_by("full_name")[:12]
            results = [
                {
                    "id": str(patient.pk),
                    "text": f"{patient.display_name} - {patient.masked_cpf or 's/ CPF'}",
                    "record": patient.record_number,
                }
                for patient in queryset
            ]
        return JsonResponse({"results": results})


class PatientExportView(ClinicViewMixin, View):
    """Exporta os dados do paciente (LGPD art. 18, portabilidade)."""

    required_permission = "patient.view_sensitive"

    def get(self, request, pk):
        from apps.lgpd.services import build_patient_export

        patient = get_object_or_404(Patient.objects.all(), pk=pk)
        payload = build_patient_export(patient)
        log_action(
            AuditAction.EXPORT,
            obj=patient,
            description="Exportacao dos dados do paciente (LGPD)",
            request=request,
            is_sensitive=True,
        )
        response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
        response["Content-Disposition"] = (
            f'attachment; filename="paciente-{patient.record_number}.json"'
        )
        return response
