"""Prontuario eletronico configuravel, evolucoes e prescricoes."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import ActiveStatusMixin, BaseModel, TenantModel


class RecordTemplate(TenantModel, ActiveStatusMixin):
    """
    Modelo (formulario) de prontuario definido por schema JSON.

    Permite que cada clinica tenha seus proprios campos sem alteracao de
    codigo ou de banco de dados.
    """

    name = models.CharField("nome", max_length=120)
    description = models.CharField("descricao", max_length=250, blank=True)
    schema = models.JSONField("estrutura", default=dict)
    specialty = models.ForeignKey(
        "clinics.Specialty",
        verbose_name="especialidade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="record_templates",
    )
    is_default = models.BooleanField("modelo padrao", default=False)

    class Meta:
        verbose_name = "modelo de prontuario"
        verbose_name_plural = "modelos de prontuario"
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_record_template_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        sections = (self.schema or {}).get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValidationError({"schema": "O modelo precisa de ao menos uma secao."})
        for section in sections:
            if not isinstance(section.get("fields"), list):
                raise ValidationError({"schema": "Cada secao precisa de uma lista de campos."})

    def fields(self):
        for section in (self.schema or {}).get("sections", []):
            for field in section.get("fields", []):
                yield section.get("title", ""), field


class MedicalRecord(TenantModel):
    """
    Prontuario do paciente na clinica (um por paciente).

    Os atendimentos ficam em :class:`MedicalRecordEntry`.
    """

    patient = models.OneToOneField(
        "patients.Patient",
        verbose_name="paciente",
        on_delete=models.CASCADE,
        related_name="medical_record",
    )
    opened_at = models.DateTimeField("aberto em", auto_now_add=True)
    summary = models.TextField("resumo clinico", blank=True)
    alerts = models.TextField("alertas importantes", blank=True)

    class Meta:
        verbose_name = "prontuario"
        verbose_name_plural = "prontuarios"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Prontuario de {self.patient.display_name}"

    @property
    def entries_count(self) -> int:
        return self.entries.filter(is_draft=False).count()


class MedicalRecordEntry(TenantModel):
    """
    Registro de um atendimento.

    Depois de assinado, o conteudo so pode ser alterado dentro da janela
    configurada pela clinica e sempre gerando uma nova versao em
    :class:`RecordEntryRevision` (o historico nunca e sobrescrito).
    """

    record = models.ForeignKey(
        MedicalRecord, verbose_name="prontuario", on_delete=models.CASCADE, related_name="entries"
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        verbose_name="agendamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="record_entries",
    )
    professional = models.ForeignKey(
        "professionals.Professional",
        verbose_name="profissional",
        on_delete=models.PROTECT,
        related_name="record_entries",
    )
    template = models.ForeignKey(
        RecordTemplate,
        verbose_name="modelo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    title = models.CharField("titulo", max_length=140, blank=True)
    data = models.JSONField("conteudo", default=dict)
    attended_at = models.DateTimeField("data do atendimento", default=timezone.now, db_index=True)

    is_draft = models.BooleanField("rascunho", default=True, db_index=True)
    signed_at = models.DateTimeField("assinado em", null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    signature_hash = models.CharField("hash da assinatura", max_length=64, blank=True,
                                      editable=False)
    version = models.PositiveIntegerField("versao", default=1, editable=False)

    class Meta:
        verbose_name = "registro de atendimento"
        verbose_name_plural = "registros de atendimento"
        ordering = ["-attended_at"]
        indexes = [
            models.Index(fields=["clinic", "-attended_at"]),
            models.Index(fields=["record", "-attended_at"]),
            models.Index(fields=["professional", "-attended_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.title or 'Atendimento'} - {self.attended_at:%d/%m/%Y}"

    @property
    def patient(self):
        return self.record.patient

    @property
    def is_signed(self) -> bool:
        return self.signed_at is not None

    def editable_until(self):
        if not self.signed_at:
            return None
        settings_obj = getattr(self.clinic, "settings", None)
        hours = settings_obj.record_lock_hours if settings_obj else 24
        return self.signed_at + timedelta(hours=hours)

    def can_be_edited_by(self, user) -> bool:
        """
        Regras de edicao:

        * rascunho: apenas o profissional autor;
        * assinado: o autor, dentro da janela de correcao da clinica;
        * fora da janela: ninguem edita (somente novo registro de retificacao).
        """
        if self.professional.user_id and self.professional.user_id != getattr(user, "pk", None):
            return False
        if not self.is_signed:
            return True
        limit = self.editable_until()
        return bool(limit and timezone.now() <= limit)

    def compute_signature(self) -> str:
        payload = f"{self.pk}|{self.professional_id}|{self.attended_at}|{self.data}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def sign(self, user) -> None:
        self.is_draft = False
        self.signed_at = timezone.now()
        self.signed_by = user
        self.signature_hash = self.compute_signature()
        self.save(
            update_fields=[
                "is_draft",
                "signed_at",
                "signed_by",
                "signature_hash",
                "updated_at",
            ]
        )

    def snapshot(self, user, reason: str = "") -> "RecordEntryRevision":
        """Guarda a versao atual antes de aplicar uma alteracao."""
        revision = RecordEntryRevision.objects.create(
            clinic_id=self.clinic_id,
            entry=self,
            version=self.version,
            data=self.data,
            title=self.title,
            changed_by=user,
            reason=reason,
        )
        self.version += 1
        return revision


class VitalSigns(TenantModel):
    """Sinais vitais registrados num atendimento (IMC calculado automaticamente)."""

    entry = models.OneToOneField(
        MedicalRecordEntry, verbose_name="atendimento", on_delete=models.CASCADE,
        related_name="vital_signs",
    )
    systolic_pressure = models.PositiveSmallIntegerField(
        "pressao sistolica (mmHg)", null=True, blank=True
    )
    diastolic_pressure = models.PositiveSmallIntegerField(
        "pressao diastolica (mmHg)", null=True, blank=True
    )
    heart_rate = models.PositiveSmallIntegerField("freq. cardiaca (bpm)", null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(
        "freq. respiratoria (irpm)", null=True, blank=True
    )
    temperature = models.DecimalField(
        "temperatura (C)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    oxygen_saturation = models.PositiveSmallIntegerField("saturacao O2 (%)", null=True, blank=True)
    weight_kg = models.DecimalField("peso (kg)", max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.PositiveSmallIntegerField("altura (cm)", null=True, blank=True)
    glucose = models.PositiveSmallIntegerField("glicemia (mg/dL)", null=True, blank=True)
    notes = models.CharField("observacoes", max_length=250, blank=True)

    class Meta:
        verbose_name = "sinais vitais"
        verbose_name_plural = "sinais vitais"

    def __str__(self) -> str:
        return f"Sinais vitais - {self.entry_id}"

    @property
    def bmi(self):
        if not self.weight_kg or not self.height_cm:
            return None
        height_m = Decimal(self.height_cm) / Decimal("100")
        if height_m <= 0:
            return None
        return (Decimal(self.weight_kg) / (height_m * height_m)).quantize(Decimal("0.1"))

    @property
    def bmi_classification(self) -> str:
        bmi = self.bmi
        if bmi is None:
            return ""
        if bmi < Decimal("18.5"):
            return "Abaixo do peso"
        if bmi < Decimal("25.0"):
            return "Peso normal"
        if bmi < Decimal("30.0"):
            return "Sobrepeso"
        if bmi < Decimal("35.0"):
            return "Obesidade grau I"
        if bmi < Decimal("40.0"):
            return "Obesidade grau II"
        return "Obesidade grau III"


class CIDCode(BaseModel):
    """
    Codigo de diagnostico (CID-10) para busca/autocomplete no prontuario.

    Tabela de referencia global (nao pertence a uma clinica especifica,
    como qualquer nomenclatura medica padrao) com um conjunto curado dos
    codigos mais usados no dia a dia -- o campo de diagnostico no
    prontuario sempre aceita texto livre tambem, entao a ausencia de um
    codigo aqui nunca bloqueia o profissional.
    """

    code = models.CharField("codigo", max_length=10, unique=True, db_index=True)
    description = models.CharField("descricao", max_length=250)
    is_active = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "codigo CID"
        verbose_name_plural = "codigos CID"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.description}"


class RecordEntryRevision(TenantModel):
    """Historico imutavel de versoes de um registro de atendimento."""

    entry = models.ForeignKey(
        MedicalRecordEntry, on_delete=models.CASCADE, related_name="revisions"
    )
    version = models.PositiveIntegerField("versao")
    title = models.CharField(max_length=140, blank=True)
    data = models.JSONField(default=dict)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.CharField("motivo da alteracao", max_length=250, blank=True)

    class Meta:
        verbose_name = "versao do registro"
        verbose_name_plural = "versoes do registro"
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"v{self.version} de {self.entry_id}"


class Prescription(TenantModel):
    """Prescricao/receituario emitido em um atendimento."""

    class Kind(models.TextChoices):
        SIMPLE = "simple", "Receita simples"
        CONTROLLED = "controlled", "Receita de controle especial"
        GUIDANCE = "guidance", "Orientacoes"
        CERTIFICATE = "certificate", "Atestado"
        DECLARATION = "declaration", "Declaracao"
        REFERRAL = "referral", "Encaminhamento"
        CLINICAL_REPORT = "clinical_report", "Relatorio clinico"

    record_entry = models.ForeignKey(
        MedicalRecordEntry,
        verbose_name="atendimento",
        on_delete=models.CASCADE,
        related_name="prescriptions",
        null=True,
        blank=True,
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="prescriptions"
    )
    professional = models.ForeignKey(
        "professionals.Professional", on_delete=models.PROTECT, related_name="prescriptions"
    )
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.SIMPLE)
    content = models.TextField("conteudo", help_text="Um item por linha.")
    instructions = models.TextField("orientacoes", blank=True)
    valid_until = models.DateField("valido ate", null=True, blank=True)
    issued_at = models.DateTimeField("emitida em", default=timezone.now)
    released_to_patient = models.BooleanField("liberada no portal", default=True)

    class Meta:
        verbose_name = "prescricao"
        verbose_name_plural = "prescricoes"
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} - {self.patient.display_name}"

    @property
    def items(self):
        return [line.strip() for line in (self.content or "").splitlines() if line.strip()]
