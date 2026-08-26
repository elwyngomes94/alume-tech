"""Solicitacao de exames e registro de resultados."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ActiveStatusMixin, TenantModel


class Examination(TenantModel, ActiveStatusMixin):
    """Catalogo de exames que a clinica costuma solicitar."""

    name = models.CharField("exame", max_length=160)
    code = models.CharField("codigo (TUSS/interno)", max_length=40, blank=True)
    category = models.CharField("categoria", max_length=80, blank=True)
    preparation = models.TextField("preparo", blank=True)

    class Meta:
        verbose_name = "exame (catalogo)"
        verbose_name_plural = "exames (catalogo)"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_examination_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class ExaminationRequest(TenantModel):
    """Solicitacao de exames emitida por um profissional."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Solicitado"
        COLLECTED = "collected", "Coletado/realizado"
        PARTIAL = "partial", "Resultado parcial"
        COMPLETED = "completed", "Concluido"
        CANCELED = "canceled", "Cancelado"

    class Priority(models.TextChoices):
        ROUTINE = "routine", "Rotina"
        PRIORITY = "priority", "Prioritario"
        URGENT = "urgent", "Urgente"

    patient = models.ForeignKey(
        "patients.Patient", verbose_name="paciente", on_delete=models.CASCADE,
        related_name="examination_requests",
    )
    professional = models.ForeignKey(
        "professionals.Professional",
        verbose_name="solicitante",
        on_delete=models.PROTECT,
        related_name="examination_requests",
    )
    record_entry = models.ForeignKey(
        "medical_records.MedicalRecordEntry",
        verbose_name="atendimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="examination_requests",
    )
    number = models.PositiveIntegerField("numero", editable=False, db_index=True)
    clinical_indication = models.TextField("indicacao/justificativa clinica")
    observations = models.TextField("observacoes", blank=True)
    priority = models.CharField(
        "prioridade", max_length=20, choices=Priority.choices, default=Priority.ROUTINE
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True
    )
    requested_at = models.DateTimeField("solicitado em", default=timezone.now)
    released_to_patient = models.BooleanField("liberado no portal", default=True)
    signature_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        verbose_name = "solicitacao de exame"
        verbose_name_plural = "solicitacoes de exame"
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "number"], name="uniq_examination_request_number_per_clinic"
            )
        ]
        indexes = [models.Index(fields=["clinic", "-requested_at"])]

    def __str__(self) -> str:
        return f"Solicitacao #{self.number} - {self.patient.display_name}"

    def save(self, *args, **kwargs):
        if not self.number:
            from apps.core.tenancy import get_current_tenant_id

            clinic_id = self.clinic_id or get_current_tenant_id()
            last = (
                ExaminationRequest.all_objects.filter(clinic_id=clinic_id)
                .order_by("-number")
                .values_list("number", flat=True)
                .first()
            )
            self.number = (last or 0) + 1
        return super().save(*args, **kwargs)

    @property
    def items_list(self):
        return self.items.all()


class ExaminationRequestItem(TenantModel):
    """Exame individual dentro de uma solicitacao."""

    request = models.ForeignKey(
        ExaminationRequest, on_delete=models.CASCADE, related_name="items"
    )
    examination = models.ForeignKey(
        Examination, on_delete=models.SET_NULL, null=True, blank=True, related_name="request_items"
    )
    name = models.CharField("exame", max_length=160)
    quantity = models.PositiveSmallIntegerField("quantidade", default=1)
    notes = models.CharField("observacao", max_length=200, blank=True)

    class Meta:
        verbose_name = "item da solicitacao"
        verbose_name_plural = "itens da solicitacao"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ExaminationResult(TenantModel):
    """Resultado anexado a uma solicitacao."""

    request = models.ForeignKey(
        ExaminationRequest, on_delete=models.CASCADE, related_name="results"
    )
    item = models.ForeignKey(
        ExaminationRequestItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="results",
    )
    document = models.ForeignKey(
        "documents.Document",
        verbose_name="arquivo do resultado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="examination_results",
    )
    summary = models.TextField("resumo/laudo", blank=True)
    result_date = models.DateField("data do resultado", null=True, blank=True)
    is_abnormal = models.BooleanField("resultado alterado", default=False)
    released_to_patient = models.BooleanField("liberado ao paciente", default=False)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        verbose_name = "resultado de exame"
        verbose_name_plural = "resultados de exame"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Resultado de {self.request}"
