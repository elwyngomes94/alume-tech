"""Notificacoes internas e fila de envio por canais externos."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel, TenantModel


class NotificationEvent(models.TextChoices):
    APPOINTMENT_CREATED = "appointment_created", "Novo agendamento"
    APPOINTMENT_CANCELED = "appointment_canceled", "Agendamento cancelado"
    APPOINTMENT_RESCHEDULED = "appointment_rescheduled", "Agendamento remarcado"
    APPOINTMENT_CONFIRMED = "appointment_confirmed", "Agendamento confirmado"
    APPOINTMENT_REMINDER = "appointment_reminder", "Lembrete de atendimento"
    DOCUMENT_AVAILABLE = "document_available", "Novo documento disponivel"
    EXAM_RESULT = "exam_result", "Resultado de exame"
    RECORD_PENDING = "record_pending", "Prontuario pendente"
    MESSAGE = "message", "Mensagem"
    SECURITY = "security", "Alerta de seguranca"
    SYSTEM = "system", "Aviso do sistema"


class Notification(BaseModel):
    """
    Notificacao interna.

    Pode pertencer a uma clinica (contexto operacional) ou ser da plataforma
    (avisos do JJA System ao SUPERADMIN).
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="destinatario",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="clinica",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    event = models.CharField(
        "evento", max_length=32, choices=NotificationEvent.choices,
        default=NotificationEvent.SYSTEM,
    )
    title = models.CharField("titulo", max_length=140)
    message = models.TextField("mensagem", blank=True)
    url = models.CharField("link", max_length=255, blank=True)
    read_at = models.DateTimeField("lida em", null=True, blank=True, db_index=True)
    level = models.CharField(
        "nivel",
        max_length=20,
        choices=[("info", "Informacao"), ("success", "Sucesso"),
                 ("warning", "Atencao"), ("danger", "Critico")],
        default="info",
    )

    class Meta:
        verbose_name = "notificacao"
        verbose_name_plural = "notificacoes"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at", "-created_at"])]

    def __str__(self) -> str:
        return self.title

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_as_read(self) -> None:
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])


class NotificationDelivery(TenantModel):
    """
    Fila de envio por canais externos.

    A arquitetura ja contempla e-mail, WhatsApp, SMS e push; a integracao com
    o provedor e feita pelo worker Celery (``apps.notifications.tasks``).
    """

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        PUSH = "push", "Push"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Falhou"
        SKIPPED = "skipped", "Ignorado"

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries", null=True, blank=True
    )
    channel = models.CharField("canal", max_length=20, choices=Channel.choices)
    destination = models.CharField("destino", max_length=180)
    subject = models.CharField("assunto", max_length=180, blank=True)
    body = models.TextField("conteudo")
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField("tentativas", default=0)
    error_message = models.CharField("erro", max_length=250, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField("agendado para", null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "envio de notificacao"
        verbose_name_plural = "envios de notificacao"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_channel_display()} -> {self.destination}"
