"""
Motor de automacao do JJA System (Fase 1 -- Automacao Operacional).

Catalogo (`Automation`) + configuracao por clinica (`AutomationSettings`) +
historico de execucoes (`AutomationExecution`, que cumpre o papel de log e
garante idempotencia). Ver `apps/automation/services/engine.py` para o
mecanismo trigger -> condition -> action -> execution -> log.
"""
from __future__ import annotations

import secrets

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel, TenantModel


class Automation(BaseModel):
    """Catalogo global dos tipos de automacao conhecidos pelo sistema."""

    class Layer(models.TextChoices):
        OPERATIONAL = "operational", "Operacional"
        COMMUNICATION = "communication", "Comunicacao"
        MANAGEMENT = "management", "Gestao"
        INTELLIGENCE = "intelligence", "Inteligencia"
        AI = "ai", "Inteligencia artificial"

    codename = models.CharField("codigo", max_length=80, unique=True, db_index=True)
    name = models.CharField("nome", max_length=120)
    layer = models.CharField("camada", max_length=20, choices=Layer.choices)
    description = models.CharField("descricao", max_length=250, blank=True)

    class Meta:
        verbose_name = "automacao"
        verbose_name_plural = "automacoes"
        ordering = ["layer", "name"]

    def __str__(self) -> str:
        return self.name


def _generate_webhook_secret() -> str:
    return secrets.token_hex(32)


class AutomationSettings(BaseModel):
    """
    Configuracao das automacoes de uma clinica (mesmo padrao de
    ``apps.clinics.models.ClinicSettings``: uma linha por clinica, acessada
    via ``clinic.automation_settings``).
    """

    clinic = models.OneToOneField(
        "clinics.Clinic", verbose_name="clinica", on_delete=models.CASCADE,
        related_name="automation_settings",
    )
    waiting_list_auto_invite = models.BooleanField(
        "convidar lista de espera automaticamente", default=True,
        help_text=(
            "Ao cancelar um agendamento, avisa a recepcao se houver paciente "
            "compativel aguardando na lista de espera."
        ),
    )
    auto_generate_receipt = models.BooleanField(
        "gerar comprovante de pagamento automaticamente", default=True,
    )
    financial_webhook_enabled = models.BooleanField(
        "aceitar baixa automatica via webhook financeiro", default=False,
        help_text="So ative apos configurar a integracao com um provedor de pagamentos.",
    )
    financial_webhook_secret = models.CharField(
        "segredo do webhook financeiro", max_length=64, blank=True, editable=False,
    )

    class Meta:
        verbose_name = "configuracao de automacao"
        verbose_name_plural = "configuracoes de automacao"

    def __str__(self) -> str:
        return f"Automacoes de {self.clinic}"

    def save(self, *args, **kwargs):
        if not self.financial_webhook_secret:
            self.financial_webhook_secret = _generate_webhook_secret()
        super().save(*args, **kwargs)


class AutomationExecution(TenantModel):
    """
    Uma execucao de uma automacao -- cumpre o papel de log e garante
    idempotencia: a mesma automacao, na mesma clinica, com a mesma chave de
    idempotencia, nunca executa a acao de sucesso duas vezes.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Em andamento"
        SUCCESS = "success", "Sucesso"
        SKIPPED = "skipped", "Ignorada (condicao nao atendida)"
        FAILED = "failed", "Falhou"

    automation = models.ForeignKey(
        Automation, verbose_name="automacao", on_delete=models.PROTECT, related_name="executions",
    )
    idempotency_key = models.CharField("chave de idempotencia", max_length=200, db_index=True)
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    trigger_content_type = models.ForeignKey(
        ContentType, verbose_name="tipo do objeto que disparou", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    trigger_object_id = models.CharField(max_length=64, blank=True)
    trigger_object = GenericForeignKey("trigger_content_type", "trigger_object_id")
    attempts = models.PositiveSmallIntegerField("tentativas", default=0)
    last_error = models.TextField("ultimo erro", blank=True)
    result = models.JSONField("resultado", default=dict, blank=True)
    started_at = models.DateTimeField("iniciado em", auto_now_add=True)
    finished_at = models.DateTimeField("finalizado em", null=True, blank=True)

    class Meta:
        verbose_name = "execucao de automacao"
        verbose_name_plural = "execucoes de automacao"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["clinic", "-started_at"]),
            models.Index(fields=["clinic", "automation", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "automation", "idempotency_key"],
                condition=models.Q(status="success"),
                name="uniq_automation_execution_success",
            )
        ]

    def __str__(self) -> str:
        return f"{self.automation.codename} - {self.get_status_display()}"

    def mark_success(self, result: dict | None = None) -> None:
        self.status = self.Status.SUCCESS
        self.result = result or {}
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "result", "finished_at", "updated_at"])

    def mark_skipped(self, reason: str = "") -> None:
        self.status = self.Status.SKIPPED
        self.result = {"reason": reason} if reason else {}
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "result", "finished_at", "updated_at"])

    def mark_failed(self, error: str) -> None:
        self.status = self.Status.FAILED
        self.attempts += 1
        self.last_error = error[:2000]
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "attempts", "last_error", "finished_at", "updated_at"])
