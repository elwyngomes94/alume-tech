"""
Chamada de pacientes: a "senha" gerada no check-in.

Reaproveita a maquina de estados que ja existe em
``apps.scheduling.models.Appointment`` (CHECKED_IN -> CALLED ->
IN_PROGRESS -> COMPLETED/CANCELED/NO_SHOW) em vez de duplicar status e
horarios aqui -- ``CallTicket`` guarda apenas o que o agendamento nao tem:
numero da senha, prioridade, token de acesso publico e contagem de
chamadas.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class CallTicket(TenantModel):
    """Senha de atendimento vinculada a um agendamento do dia."""

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        LEGAL = "legal", "Prioridade legal"
        ELDERLY = "elderly", "Idoso"
        PREGNANT = "pregnant", "Gestante"
        PCD = "pcd", "PCD"
        EMERGENCY = "emergency", "Emergencia"

    #: ordem de atendimento -- menor valor primeiro (Emergencia sempre na
    #: frente; entre os demais, o desempate e pela hora do check-in).
    PRIORITY_WEIGHT = {
        Priority.EMERGENCY: 0,
        Priority.PCD: 1,
        Priority.PREGNANT: 1,
        Priority.ELDERLY: 1,
        Priority.LEGAL: 1,
        Priority.NORMAL: 2,
    }

    appointment = models.OneToOneField(
        "scheduling.Appointment",
        verbose_name="agendamento",
        on_delete=models.CASCADE,
        related_name="call_ticket",
    )
    ticket_number = models.CharField("senha", max_length=10, db_index=True)
    priority = models.CharField(
        "prioridade", max_length=12, choices=Priority.choices, default=Priority.NORMAL
    )
    access_token = models.CharField("token de acesso", max_length=64, unique=True, db_index=True)
    token_expires_at = models.DateTimeField("token expira em")
    call_count = models.PositiveIntegerField("vezes chamado", default=0)

    class Meta:
        verbose_name = "senha de atendimento"
        verbose_name_plural = "senhas de atendimento"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.ticket_number

    @property
    def priority_weight(self) -> int:
        return self.PRIORITY_WEIGHT.get(self.priority, 2)


class CallEvent(TenantModel):
    """
    Historico do que a maquina de estados do agendamento nao registra:
    apenas a "rechamada" (nao muda o status, que permanece CALLED).
    """

    class Kind(models.TextChoices):
        CALLED = "called", "Chamado"
        RECALLED = "recalled", "Rechamado"

    ticket = models.ForeignKey(CallTicket, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "evento de chamada"
        verbose_name_plural = "eventos de chamada"
        ordering = ["-created_at"]


class PushSubscription(TenantModel):
    """
    Inscricao de Web Push do navegador do paciente durante a visita atual.

    Escopada a senha (nao ao cadastro do paciente/portal): o objetivo e
    avisar quem esta esperando por *esta* senha, no aparelho que ele tem
    em maos agora -- nao um canal permanente entre visitas.
    """

    ticket = models.ForeignKey(CallTicket, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField("endpoint", max_length=500, unique=True)
    p256dh = models.CharField("chave p256dh", max_length=255)
    auth = models.CharField("chave auth", max_length=255)
    user_agent = models.CharField("user agent", max_length=255, blank=True)

    class Meta:
        verbose_name = "inscricao de push"
        verbose_name_plural = "inscricoes de push"


class CallPanelConfig(TenantModel):
    """Configuracao da fila de chamada por clinica."""

    class DisplayMode(models.TextChoices):
        TICKET_ONLY = "ticket_only", "Somente a senha"
        INITIALS = "initials", "Iniciais do paciente"
        FULL_NAME = "full_name", "Nome completo"

    clinic = models.OneToOneField(
        "clinics.Clinic",
        verbose_name="clinica",
        on_delete=models.CASCADE,
        related_name="calling_config",
        editable=False,
    )
    ticket_prefix = models.CharField("prefixo da senha", max_length=3, default="A")
    display_mode = models.CharField(
        "exibicao no painel", max_length=12, choices=DisplayMode.choices,
        default=DisplayMode.TICKET_ONLY,
    )
    sound_enabled = models.BooleanField("som no painel", default=True)
    no_show_minutes = models.PositiveIntegerField(
        "minutos para alerta de nao comparecimento", default=15
    )

    class Meta:
        verbose_name = "configuracao de chamada"
        verbose_name_plural = "configuracoes de chamada"

    def __str__(self) -> str:
        return f"Configuracao de chamada - {self.clinic}"
