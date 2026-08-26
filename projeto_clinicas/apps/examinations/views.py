"""Views de solicitacao de exames e resultados."""
from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from apps.audit.models import AuditAction
from apps.audit.services import log_action
from apps.core.mixins import ClinicViewMixin
from apps.documents.models import Document, DocumentCategory
from apps.examinations.forms import (
    ExaminationForm,
    ExaminationRequestForm,
    ExaminationResultForm,
)
from apps.examinations.models import Examination, ExaminationRequest, ExaminationResult
from apps.medical_records.services import assert_can_access_patient_record


class ExaminationRequestListView(ClinicViewMixin, ListView):
    model = ExaminationRequest
    template_name = "examinations/request_list.html"
    context_object_name = "requests"
    paginate_by = 25
    required_permission = "examination.view"

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("patient", "professional")
            .prefetch_related("items")
        )
        user = self.request.user
        if not user.has_clinic_perm("appointment.view_all", self.request.clinic):
            queryset = queryset.filter(professional__user=user)
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(patient__full_name__icontains=search) | Q(items__name__icontains=search)
            ).distinct()
        return queryset.order_by("-requested_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = ExaminationRequest.Status.choices
        return context


class ExaminationRequestCreateView(ClinicViewMixin, CreateView):
    model = ExaminationRequest
    form_class = ExaminationRequestForm
    template_name = "examinations/request_form.html"
    required_permission = "examination.request"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        patient_id = self.request.GET.get("patient")
        if patient_id:
            from apps.patients.models import Patient

            kwargs["patient"] = Patient.objects.filter(pk=patient_id).first()
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        patient = form.cleaned_data["patient"]
        assert_can_access_patient_record(self.request.user, self.request.clinic, patient)
        request_obj = form.save(commit=False)
        request_obj.clinic = self.request.clinic
        entry_id = self.request.GET.get("entry")
        if entry_id:
            from apps.medical_records.models import MedicalRecordEntry

            request_obj.record_entry = MedicalRecordEntry.objects.filter(pk=entry_id).first()
        request_obj.save()
        form.save_items(request_obj)
        self.object = request_obj
        log_action(
            AuditAction.CREATE,
            obj=request_obj,
            description="Solicitacao de exames emitida",
            request=self.request,
            is_sensitive=True,
        )
        messages.success(self.request, "Solicitacao de exames registrada.")
        return redirect("examinations:request-detail", pk=request_obj.pk)


class ExaminationRequestDetailView(ClinicViewMixin, DetailView):
    model = ExaminationRequest
    template_name = "examinations/request_detail.html"
    context_object_name = "request_obj"
    required_permission = "examination.view"
    audit_object_access = True
    audit_description = "Consulta a solicitacao de exames"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("patient", "professional", "clinic")
            .prefetch_related("items", "results__document")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["result_form"] = ExaminationResultForm(request_obj=self.object)
        context["can_add_result"] = self.request.user.has_clinic_perm(
            "examination.result", self.request.clinic
        )
        return context


class ExaminationRequestPrintView(ExaminationRequestDetailView):
    template_name = "examinations/request_print.html"
    audit_description = "Impressao da solicitacao de exames"


class ExaminationResultCreateView(ClinicViewMixin, View):
    required_permission = "examination.result"

    @transaction.atomic
    def post(self, request, pk):
        request_obj = get_object_or_404(
            ExaminationRequest.objects.select_related("patient"), pk=pk
        )
        form = ExaminationResultForm(request.POST, request.FILES, request_obj=request_obj)
        if not form.is_valid():
            messages.error(request, "; ".join(
                f"{field}: {', '.join(errors)}" for field, errors in form.errors.items()
            ))
            return redirect("examinations:request-detail", pk=pk)

        result = form.save(commit=False)
        result.clinic = request.clinic
        result.request = request_obj
        result.registered_by = request.user

        uploaded = form.cleaned_data.get("file")
        if uploaded:
            category, _ = DocumentCategory.all_objects.get_or_create(
                clinic=request.clinic,
                name="Resultado de exame",
                defaults={"is_clinical": True, "visible_to_patient_default": True},
            )
            document = Document(
                clinic=request.clinic,
                patient=request_obj.patient,
                category=category,
                title=f"Resultado - solicitacao #{request_obj.number}",
                file=uploaded,
                uploaded_by=request.user,
                is_sensitive=True,
                visible_to_patient=form.cleaned_data.get("released_to_patient", False),
            )
            document.full_clean(exclude=["clinic", "original_name", "content_type", "size",
                                         "checksum"])
            document.save()
            result.document = document
            log_action(
                AuditAction.UPLOAD,
                obj=document,
                description="Upload de resultado de exame",
                request=request,
                is_sensitive=True,
            )

        result.save()
        request_obj.status = ExaminationRequest.Status.COMPLETED
        request_obj.save(update_fields=["status", "updated_at"])

        from apps.notifications.services import notify_examination_result

        notify_examination_result(result)
        messages.success(request, "Resultado registrado.")
        return redirect("examinations:request-detail", pk=pk)


class ExaminationRequestStatusView(ClinicViewMixin, View):
    required_permission = "examination.result"

    def post(self, request, pk, status):
        request_obj = get_object_or_404(ExaminationRequest.objects.all(), pk=pk)
        if status not in ExaminationRequest.Status.values:
            messages.error(request, "Status invalido.")
        else:
            request_obj.status = status
            request_obj.save(update_fields=["status", "updated_at"])
            messages.success(request, "Status atualizado.")
        return redirect("examinations:request-detail", pk=pk)


class ExaminationCatalogListView(ClinicViewMixin, ListView):
    model = Examination
    template_name = "examinations/catalog_list.html"
    context_object_name = "examinations"
    required_permission = "examination.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = ExaminationForm()
        return context


class ExaminationCatalogCreateView(ClinicViewMixin, CreateView):
    model = Examination
    form_class = ExaminationForm
    template_name = "examinations/catalog_list.html"
    required_permission = "examination.request"
    success_url = reverse_lazy("examinations:catalog-list")

    def form_valid(self, form):
        messages.success(self.request, "Exame incluido no catalogo.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Nao foi possivel incluir o exame.")
        return redirect(self.success_url)
