"""
Estrutura de apoio a LGPD (Lei 13.709/2018).

Importante: consentimento e apenas UMA das bases legais possiveis. No contexto
de saude, boa parte do tratamento se apoia em outras hipoteses (ex.: tutela da
saude, cumprimento de obrigacao legal e regulatoria). Por isso os modelos
registram a **base legal aplicada**, e nao apenas o aceite do titular.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ActiveStatusMixin, TenantModel


class LegalBasis(models.TextChoices):
    CONSENT = "consent", "Consentimento (art. 7, I / art. 11, I)"
    LEGAL_OBLIGATION = "legal_obligation", "Cumprimento de obrigacao legal (art. 7, II)"
    CONTRACT = "contract", "Execucao de contrato (art. 7, V)"
    HEALTH_PROTECTION = "health_protection", "Tutela da saude (art. 7, VIII / art. 11, II, f)"
    LEGITIMATE_INTEREST = "legitimate_interest", "Legitimo interesse (art. 7, IX)"
    RIGHTS_DEFENSE = "rights_defense", "Exercicio regular de direitos (art. 7, VI)"


class ConsentType(TenantModel, ActiveStatusMixin):
    """Tipo de termo/consentimento utilizado pela clinica."""

    name = models.CharField("nome", max_length=140)
    description = models.TextField("descricao", blank=True)
    content = models.TextField("texto do termo")
    legal_basis = models.CharField(
        "base legal", max_length=32, choices=LegalBasis.choices, default=LegalBasis.CONSENT
    )
    is_required = models.BooleanField("obrigatorio para atendimento", default=False)
    version = models.CharField("versao", max_length=20, default="1.0")

    class Meta:
        verbose_name = "tipo de consentimento"
        verbose_name_plural = "tipos de consentimento"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name", "version"],
                condition=models.Q(is_deleted=False),
                name="uniq_consent_type_version_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"


class Consent(TenantModel):
    """Registro de consentimento (ou revogacao) de um titular."""

    consent_type = models.ForeignKey(
        ConsentType, verbose_name="tipo", on_delete=models.PROTECT, related_name="consents"
    )
    patient = models.ForeignKey(
        "patients.Patient", verbose_name="paciente", on_delete=models.CASCADE,
        related_name="consents",
    )
    granted = models.BooleanField("concedido", default=True)
    granted_at = models.DateTimeField("data do aceite", default=timezone.now)
    revoked_at = models.DateTimeField("revogado em", null=True, blank=True)
    revocation_reason = models.CharField("motivo da revogacao", max_length=250, blank=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    channel = models.CharField(
        "canal de coleta",
        max_length=20,
        choices=[("in_person", "Presencial"), ("portal", "Portal do paciente"),
                 ("document", "Documento assinado")],
        default="in_person",
    )
    ip_address = models.CharField(max_length=45, blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    content_snapshot = models.TextField("texto aceito (snapshot)", blank=True)

    class Meta:
        verbose_name = "consentimento"
        verbose_name_plural = "consentimentos"
        ordering = ["-granted_at"]
        indexes = [models.Index(fields=["clinic", "patient", "-granted_at"])]

    def __str__(self) -> str:
        estado = "revogado" if self.revoked_at else ("concedido" if self.granted else "negado")
        return f"{self.consent_type.name} - {self.patient.display_name} ({estado})"

    def save(self, *args, **kwargs):
        if not self.content_snapshot and self.consent_type_id:
            self.content_snapshot = self.consent_type.content
        return super().save(*args, **kwargs)

    @property
    def is_valid(self) -> bool:
        return self.granted and self.revoked_at is None

    def revoke(self, reason: str = "") -> None:
        self.revoked_at = timezone.now()
        self.revocation_reason = reason[:250]
        self.save(update_fields=["revoked_at", "revocation_reason", "updated_at"])


class DataSubjectRequest(TenantModel):
    """Solicitacao do titular (art. 18 da LGPD)."""

    class Kind(models.TextChoices):
        ACCESS = "access", "Acesso aos dados"
        CORRECTION = "correction", "Correcao de dados"
        PORTABILITY = "portability", "Portabilidade"
        DELETION = "deletion", "Eliminacao"
        ANONYMIZATION = "anonymization", "Anonimizacao"
        REVOKE_CONSENT = "revoke_consent", "Revogacao de consentimento"
        INFORMATION = "information", "Informacao sobre compartilhamento"

    class Status(models.TextChoices):
        RECEIVED = "received", "Recebida"
        IN_PROGRESS = "in_progress", "Em analise"
        COMPLETED = "completed", "Concluida"
        REJECTED = "rejected", "Recusada"

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="data_requests",
        null=True, blank=True,
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="data_requests",
    )
    requester_name = models.CharField("titular", max_length=180)
    requester_email = models.EmailField("e-mail para resposta")
    kind = models.CharField("tipo", max_length=32, choices=Kind.choices)
    description = models.TextField("descricao do pedido", blank=True)
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    response = models.TextField("resposta", blank=True)
    due_date = models.DateField("prazo de resposta", null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "solicitacao do titular"
        verbose_name_plural = "solicitacoes do titular"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} - {self.requester_name}"

    def save(self, *args, **kwargs):
        if not self.due_date:
            from datetime import timedelta

            self.due_date = timezone.localdate() + timedelta(days=15)
        return super().save(*args, **kwargs)

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.due_date
            and self.status in (self.Status.RECEIVED, self.Status.IN_PROGRESS)
            and self.due_date < timezone.localdate()
        )


class SecurityIncident(TenantModel):
    """Registro de incidente de seguranca com dados pessoais (art. 48)."""

    class Severity(models.TextChoices):
        LOW = "low", "Baixa"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Critica"

    class Status(models.TextChoices):
        OPEN = "open", "Em apuracao"
        CONTAINED = "contained", "Contido"
        NOTIFIED = "notified", "Comunicado a ANPD/titulares"
        CLOSED = "closed", "Encerrado"

    title = models.CharField("titulo", max_length=180)
    description = models.TextField("descricao")
    severity = models.CharField("severidade", max_length=20, choices=Severity.choices,
                                default=Severity.MEDIUM)
    status = models.CharField("status", max_length=20, choices=Status.choices,
                              default=Status.OPEN)
    detected_at = models.DateTimeField("detectado em", default=timezone.now)
    affected_records = models.PositiveIntegerField("registros afetados (estimativa)", default=0)
    contains_sensitive_data = models.BooleanField("envolve dados sensiveis", default=True)
    measures_taken = models.TextField("medidas adotadas", blank=True)
    anpd_notified_at = models.DateTimeField("comunicado a ANPD em", null=True, blank=True)
    subjects_notified_at = models.DateTimeField("titulares comunicados em", null=True, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        verbose_name = "incidente de seguranca"
        verbose_name_plural = "incidentes de seguranca"
        ordering = ["-detected_at"]

    def __str__(self) -> str:
        return self.title
