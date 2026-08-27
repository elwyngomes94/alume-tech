"""Views do prontuario eletronico."""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.audit.models import AuditAction
from apps.audit.services import log_action, log_view
from apps.core.mixins import ClinicViewMixin
from apps.medical_records import services
from apps.medical_records.forms import (
    DynamicRecordEntryForm,
    PrescriptionForm,
    RecordEntryMetaForm,
    RecordTemplateForm,
    ReviseEntryForm,
    SignEntryForm,
    VitalSignsForm,
)
from apps.medical_records.models import (
    CIDCode,
    MedicalRecordEntry,
    Prescription,
    RecordTemplate,
    VitalSigns,
)
from apps.patients.models import Patient
from apps.reports.exporters import export_record_pdf


class RecordDetailView(ClinicViewMixin, TemplateView):
    """Linha do tempo do prontuario de um paciente."""

    template_name = "medical_records/record_detail.html"
    required_permission = "medicalrecord.view"

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = get_object_or_404(Patient.objects.all(), pk=self.kwargs["patient_id"])
        services.assert_can_access_patient_record(self.request.user, self.request.clinic, patient)
        record = services.get_or_create_record(patient)
        log_view(record, request=self.request, description="Abertura do prontuario")

        entries = (
            MedicalRecordEntry.objects.filter(record=record)
            .select_related("professional", "template", "appointment")
            .prefetch_related("prescriptions")
            .order_by("-attended_at")
        )
        context.update(
            {
                "patient": patient,
                "record": record,
                "entries": entries,
                "can_add": self.request.user.has_clinic_perm(
                    "medicalrecord.add", self.request.clinic
                ),
                "prescriptions": patient.prescriptions.select_related("professional")
                .order_by("-issued_at")[:20],
                "documents": patient.documents.select_related("category")
                .order_by("-created_at")[:20],
                "record_pdf_url": reverse("medical_records:record-pdf", args=[patient.pk]),
                "record_print_ack_url": reverse(
                    "medical_records:record-print-ack", args=[patient.pk]
                ),
                "record_whatsapp_text": f"Prontuario de {patient.display_name}.",
            }
        )
        if self.request.user.has_clinic_perm("examination.view", self.request.clinic):
            context["exam_requests"] = (
                patient.examination_requests.select_related("professional")
                .order_by("-requested_at")[:20]
            )
        if self.request.clinic.has_module_finance and self.request.user.has_clinic_perm(
            "appointment.payment", self.request.clinic
        ):
            from apps.finance.models import ReceivableAccount

            context["receivables"] = (
                ReceivableAccount.objects.filter(patient=patient)
                .select_related("service")
                .order_by("-service_date")[:20]
            )
        return context


class RecordExportPDFView(ClinicViewMixin, View):
    """Gera o PDF completo do prontuario (atendimentos/prescricoes/exames)."""

    required_permission = "medicalrecord.view"

    def get(self, request, patient_id):
        patient = get_object_or_404(Patient.objects.all(), pk=patient_id)
        services.assert_can_access_patient_record(request.user, request.clinic, patient)
        record = services.get_or_create_record(patient)

        entries = (
            MedicalRecordEntry.objects.filter(record=record, is_draft=False)
            .select_related("professional", "template")
            .order_by("-attended_at")
        )
        entry_rows = [
            [
                timezone.localtime(entry.attended_at).strftime("%d/%m/%Y %H:%M")
                if entry.attended_at else "-",
                entry.professional.display_name if entry.professional else "-",
                entry.template.name if entry.template else "-",
                "Assinado" if entry.is_signed else "Rascunho",
            ]
            for entry in entries
        ]

        prescriptions = patient.prescriptions.select_related("professional").order_by("-issued_at")[:50]
        prescription_rows = [
            [
                timezone.localtime(prescription.issued_at).strftime("%d/%m/%Y")
                if prescription.issued_at else "-",
                prescription.professional.display_name if prescription.professional else "-",
                prescription.get_kind_display(),
                ", ".join(prescription.items)[:120],
            ]
            for prescription in prescriptions
        ]

        exams = patient.examination_requests.select_related("professional").order_by("-requested_at")[:50]
        exam_rows = [
            [
                timezone.localtime(exam.requested_at).strftime("%d/%m/%Y")
                if exam.requested_at else "-",
                exam.professional.display_name if exam.professional else "-",
                exam.get_status_display(),
            ]
            for exam in exams
        ]

        log_action(
            AuditAction.EXPORT,
            obj=record,
            description="Exportacao do prontuario em PDF",
            request=request,
            is_sensitive=True,
        )
        return export_record_pdf(
            f"prontuario-{patient.pk}",
            patient,
            entry_rows,
            prescription_rows,
            exam_rows,
            clinic=request.clinic,
        )


class RecordPrintAckView(ClinicViewMixin, View):
    """
    So registra a auditoria de impressao (``AuditAction.PRINT``) -- o
    template chama esta rota via ``fetch()`` antes de ``window.print()``,
    para que "visualizado", "exportado" e "impresso" fiquem como acoes
    distintas na trilha de auditoria, como visualizacao/criacao/edicao ja
    ficam.
    """

    required_permission = "medicalrecord.view"

    def post(self, request, patient_id):
        patient = get_object_or_404(Patient.objects.all(), pk=patient_id)
        services.assert_can_access_patient_record(request.user, request.clinic, patient)
        record = services.get_or_create_record(patient)
        log_action(
            AuditAction.PRINT,
            obj=record,
            description="Impressao do prontuario",
            request=request,
            is_sensitive=True,
        )
        return JsonResponse({"ok": True})


class RecordEntryCreateView(ClinicViewMixin, View):
    """Novo atendimento no prontuario, com formulario dinamico."""

    required_permission = "medicalrecord.add"
    template_name = "medical_records/entry_form.html"

    def get_objects(self):
        patient = get_object_or_404(Patient.objects.all(), pk=self.kwargs["patient_id"])
        services.assert_can_access_patient_record(self.request.user, self.request.clinic, patient)
        record = services.get_or_create_record(patient)
        return patient, record

    def get_template_obj(self, request, patient):
        template_id = request.POST.get("template") or request.GET.get("template")
        queryset = RecordTemplate.objects.filter(is_active=True)
        if template_id:
            template = queryset.filter(pk=template_id).first()
            if template:
                return template
        professional = services.professional_for(request.user, request.clinic)
        return services.default_template(request.clinic, professional)

    def get(self, request, patient_id):
        patient, record = self.get_objects()
        template = self.get_template_obj(request, patient)
        if template is None:
            messages.error(
                request,
                "Nenhum modelo de prontuario cadastrado. Configure em Prontuario > Modelos.",
            )
            return redirect("medical_records:template-list")
        meta_form = RecordEntryMetaForm(user=request.user, initial={
            "template": template, "attended_at": timezone.localtime()
        })
        dynamic_form = DynamicRecordEntryForm(template=template)
        vital_form = VitalSignsForm()
        return render(
            request,
            self.template_name,
            {
                "patient": patient,
                "record": record,
                "meta_form": meta_form,
                "dynamic_form": dynamic_form,
                "vital_form": vital_form,
                "template_obj": template,
                "templates": RecordTemplate.objects.filter(is_active=True),
            },
        )

    def post(self, request, patient_id):
        patient, record = self.get_objects()
        template = self.get_template_obj(request, patient)
        meta_form = RecordEntryMetaForm(request.POST, user=request.user)
        dynamic_form = DynamicRecordEntryForm(request.POST, template=template)
        vital_form = VitalSignsForm(request.POST)

        if meta_form.is_valid() and dynamic_form.is_valid() and vital_form.is_valid():
            entry = meta_form.save(commit=False)
            entry.clinic = request.clinic
            entry.record = record
            entry.template = template
            entry.data = dynamic_form.to_data()
            entry.is_draft = request.POST.get("action") != "sign"
            appointment_id = request.POST.get("appointment")
            if appointment_id:
                from apps.scheduling.models import Appointment

                entry.appointment = Appointment.objects.filter(pk=appointment_id).first()
            entry.save()
            if any(vital_form.cleaned_data.values()):
                vitals = vital_form.save(commit=False)
                vitals.clinic = request.clinic
                vitals.entry = entry
                vitals.save()
            if request.POST.get("action") == "sign":
                entry.sign(request.user)
                log_action(
                    AuditAction.UPDATE,
                    obj=entry,
                    description="Registro de prontuario assinado",
                    request=request,
                    is_sensitive=True,
                )
                messages.success(request, "Atendimento registrado e assinado.")
            else:
                messages.success(request, "Rascunho salvo.")
            return redirect("medical_records:entry-detail", pk=entry.pk)

        messages.error(request, "Verifique os campos obrigatorios.")
        return render(
            request,
            self.template_name,
            {
                "patient": patient,
                "record": record,
                "meta_form": meta_form,
                "dynamic_form": dynamic_form,
                "vital_form": vital_form,
                "template_obj": template,
                "templates": RecordTemplate.objects.filter(is_active=True),
            },
        )


class RecordEntryDetailView(ClinicViewMixin, DetailView):
    model = MedicalRecordEntry
    template_name = "medical_records/entry_detail.html"
    context_object_name = "entry"
    required_permission = "medicalrecord.view"
    audit_object_access = True
    audit_description = "Consulta a registro de atendimento"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("record__patient", "professional", "template", "signed_by")
            .prefetch_related("prescriptions", "revisions")
        )

    def get_object(self, queryset=None):
        entry = super().get_object(queryset)
        services.assert_can_access_patient_record(
            self.request.user, self.request.clinic, entry.record.patient
        )
        return entry

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self.object
        context["patient"] = entry.record.patient
        context["can_edit"] = entry.can_be_edited_by(self.request.user) and (
            self.request.user.has_clinic_perm("medicalrecord.change", self.request.clinic)
        )
        context["sign_form"] = SignEntryForm()
        context["values"] = self._readable_values(entry)
        context["vital_signs"] = VitalSigns.objects.filter(entry=entry).first()
        return context

    @staticmethod
    def _readable_values(entry):
        """
        Casa os dados gravados com os rotulos do modelo usado.

        Retorna dicts (nao tuplas) porque o template usa ``{% regroup %}``,
        que le atributos/chaves, nao indices de tupla.
        """
        result = []
        if not entry.template:
            return [
                {"section": "", "label": key, "value": value}
                for key, value in (entry.data or {}).items()
            ]
        for section_title, field in entry.template.fields():
            value = (entry.data or {}).get(field["name"], "")
            if value in ("", None, []):
                continue
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            result.append(
                {
                    "section": section_title,
                    "label": field.get("label", field["name"]),
                    "value": value,
                }
            )
        return result


class RecordEntryUpdateView(ClinicViewMixin, View):
    """Edicao/retificacao de um registro (gera nova versao no historico)."""

    required_permission = "medicalrecord.change"
    template_name = "medical_records/entry_form.html"

    def get_entry(self):
        entry = get_object_or_404(
            MedicalRecordEntry.objects.select_related("record__patient", "template"),
            pk=self.kwargs["pk"],
        )
        services.assert_can_access_patient_record(
            self.request.user, self.request.clinic, entry.record.patient
        )
        if not entry.can_be_edited_by(self.request.user):
            raise PermissionDenied(
                "Este registro nao pode mais ser editado. Registre uma nova evolucao "
                "de retificacao."
            )
        return entry

    def get(self, request, pk):
        entry = self.get_entry()
        meta_form = RecordEntryMetaForm(instance=entry, user=request.user)
        dynamic_form = DynamicRecordEntryForm(template=entry.template, initial_data=entry.data)
        vital_form = VitalSignsForm(instance=VitalSigns.objects.filter(entry=entry).first())
        return render(
            request,
            self.template_name,
            {
                "patient": entry.record.patient,
                "record": entry.record,
                "entry": entry,
                "meta_form": meta_form,
                "dynamic_form": dynamic_form,
                "vital_form": vital_form,
                "template_obj": entry.template,
                "revise_form": ReviseEntryForm(),
            },
        )

    def post(self, request, pk):
        entry = self.get_entry()
        meta_form = RecordEntryMetaForm(request.POST, instance=entry, user=request.user)
        dynamic_form = DynamicRecordEntryForm(request.POST, template=entry.template)
        existing_vitals = VitalSigns.objects.filter(entry=entry).first()
        vital_form = VitalSignsForm(request.POST, instance=existing_vitals)
        if meta_form.is_valid() and dynamic_form.is_valid() and vital_form.is_valid():
            entry.snapshot(request.user, reason=request.POST.get("reason", ""))
            entry = meta_form.save(commit=False)
            entry.data = dynamic_form.to_data()
            if request.POST.get("action") == "sign":
                entry.is_draft = False
                entry.save()
                entry.sign(request.user)
            else:
                entry.save()
            if any(vital_form.cleaned_data.values()):
                vitals = vital_form.save(commit=False)
                vitals.clinic = request.clinic
                vitals.entry = entry
                vitals.save()
            elif existing_vitals is not None:
                # Exclusao definitiva (nao logica): sinais vitais nao sao um
                # registro clinico independente -- sao um componente do
                # atendimento, cujo historico ja e preservado via
                # ``RecordEntryRevision``. Excluir apenas logicamente
                # impediria recriar o registro (OneToOneField unico).
                existing_vitals.delete(hard=True)
            log_action(
                AuditAction.UPDATE,
                obj=entry,
                description="Registro de prontuario alterado",
                request=request,
                is_sensitive=True,
                changes={"motivo": request.POST.get("reason", "")},
            )
            messages.success(request, "Registro atualizado (nova versao gerada).")
            return redirect("medical_records:entry-detail", pk=entry.pk)
        messages.error(request, "Verifique os campos obrigatorios.")
        return render(
            request,
            self.template_name,
            {
                "patient": entry.record.patient,
                "record": entry.record,
                "entry": entry,
                "meta_form": meta_form,
                "dynamic_form": dynamic_form,
                "template_obj": entry.template,
                "revise_form": ReviseEntryForm(),
            },
        )


class RecordEntrySignView(ClinicViewMixin, View):
    required_permission = "medicalrecord.sign"

    def post(self, request, pk):
        entry = get_object_or_404(
            MedicalRecordEntry.objects.select_related("record__patient"), pk=pk
        )
        services.assert_can_access_patient_record(
            request.user, request.clinic, entry.record.patient
        )
        if entry.is_signed:
            messages.info(request, "Este registro ja esta assinado.")
        else:
            entry.sign(request.user)
            log_action(
                AuditAction.UPDATE,
                obj=entry,
                description="Registro assinado",
                request=request,
                is_sensitive=True,
            )
            messages.success(request, "Registro assinado.")
        return redirect("medical_records:entry-detail", pk=pk)


class PrescriptionCreateView(ClinicViewMixin, CreateView):
    model = Prescription
    form_class = PrescriptionForm
    template_name = "medical_records/prescription_form.html"
    required_permission = "prescription.add"

    def dispatch(self, request, *args, **kwargs):
        self.entry = None
        return super().dispatch(request, *args, **kwargs)

    def get_entry(self):
        if self.entry is None:
            self.entry = get_object_or_404(
                MedicalRecordEntry.objects.select_related("record__patient", "professional"),
                pk=self.kwargs["entry_id"],
            )
            services.assert_can_access_patient_record(
                self.request.user, self.request.clinic, self.entry.record.patient
            )
        return self.entry

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entry"] = self.get_entry()
        context["patient"] = self.get_entry().record.patient
        return context

    def form_valid(self, form):
        entry = self.get_entry()
        prescription = form.save(commit=False)
        prescription.clinic = self.request.clinic
        prescription.record_entry = entry
        prescription.patient = entry.record.patient
        prescription.professional = entry.professional
        prescription.save()
        self.object = prescription
        messages.success(self.request, "Prescricao emitida.")
        return redirect("medical_records:prescription-detail", pk=prescription.pk)


class PrescriptionDetailView(ClinicViewMixin, DetailView):
    model = Prescription
    template_name = "medical_records/prescription_print.html"
    context_object_name = "prescription"
    required_permission = "medicalrecord.view"
    audit_object_access = True
    audit_description = "Impressao/consulta de prescricao"

    def get_queryset(self):
        return super().get_queryset().select_related("patient", "professional", "clinic")


class CIDSearchView(ClinicViewMixin, View):
    """
    Autocomplete de codigos CID-10 usado no campo de diagnostico do
    prontuario. O campo em si sempre aceita texto livre -- isto e apenas
    uma ajuda, nunca um bloqueio.
    """

    required_permission = "medicalrecord.view"

    def get(self, request):
        term = request.GET.get("q", "").strip()
        results = []
        if len(term) >= 2:
            queryset = CIDCode.objects.filter(is_active=True).filter(
                Q(code__istartswith=term) | Q(description__icontains=term)
            ).order_by("code")[:15]
            results = [
                {"id": item.code, "text": f"{item.code} - {item.description}"}
                for item in queryset
            ]
        return JsonResponse({"results": results})


class RecordTemplateListView(ClinicViewMixin, ListView):
    model = RecordTemplate
    template_name = "medical_records/template_list.html"
    context_object_name = "templates"
    required_permission = "template.manage"

    def get_queryset(self):
        return super().get_queryset().select_related("specialty").order_by("-is_default", "name")


class RecordTemplateCreateView(ClinicViewMixin, CreateView):
    model = RecordTemplate
    form_class = RecordTemplateForm
    template_name = "medical_records/template_form.html"
    required_permission = "template.manage"
    success_url = reverse_lazy("medical_records:template-list")

    def form_valid(self, form):
        messages.success(self.request, "Modelo de prontuario criado.")
        return super().form_valid(form)


class RecordTemplateUpdateView(ClinicViewMixin, UpdateView):
    model = RecordTemplate
    form_class = RecordTemplateForm
    template_name = "medical_records/template_form.html"
    required_permission = "template.manage"
    success_url = reverse_lazy("medical_records:template-list")


class RecordTemplateSeedView(ClinicViewMixin, View):
    """Cria os modelos sugeridos para o tipo da clinica."""

    required_permission = "template.manage"

    def post(self, request):
        created = services.ensure_default_templates(request.clinic)
        messages.success(request, f"{created} modelo(s) criado(s) a partir do catalogo padrao.")
        return redirect("medical_records:template-list")
