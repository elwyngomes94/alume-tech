"""Agenda: disponibilidade, bloqueios, agendamentos e lista de espera."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.managers import TenantManager, TenantQuerySet
from apps.core.models import ActiveStatusMixin, TenantModel

WEEKDAY_CHOICES = [
    (0, "Segunda-feira"),
    (1, "Terca-feira"),
    (2, "Quarta-feira"),
    (3, "Quinta-feira"),
    (4, "Sexta-feira"),
    (5, "Sabado"),
    (6, "Domingo"),
]


class ScheduleTemplate(TenantModel, ActiveStatusMixin):
    """Disponibilidade recorrente de um profissional (grade semanal)."""

    professional = models.ForeignKey(
        "professionals.Professional",
        verbose_name="profissional",
        on_delete=models.CASCADE,
        related_name="schedule_templates",
    )
    weekday = models.PositiveSmallIntegerField("dia da semana", choices=WEEKDAY_CHOICES)
    start_time = models.TimeField("inicio")
    end_time = models.TimeField("fim")
    slot_minutes = models.PositiveIntegerField("intervalo entre horarios (min)", default=30)
    max_appointments = models.PositiveIntegerField(
        "maximo de atendimentos no dia", null=True, blank=True,
        help_text="Vazio = sem limite. A geracao de horarios para de gerar novos "
        "horarios (livres ou ocupados) assim que atingir este total.",
    )
    break_start = models.TimeField("inicio do intervalo", null=True, blank=True)
    break_end = models.TimeField("fim do intervalo", null=True, blank=True)
    room = models.ForeignKey(
        "clinics.Room",
        verbose_name="sala",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_templates",
    )
    valid_from = models.DateField("valido a partir de", null=True, blank=True)
    valid_to = models.DateField("valido ate", null=True, blank=True)

    class Meta:
        verbose_name = "disponibilidade"
        verbose_name_plural = "disponibilidades"
        ordering = ["weekday", "start_time"]
        indexes = [models.Index(fields=["clinic", "professional", "weekday"])]

    def __str__(self) -> str:
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError({"end_time": "O horario final deve ser maior que o inicial."})
        if bool(self.break_start) != bool(self.break_end):
            raise ValidationError({"break_end": "Informe inicio e fim do intervalo."})
        if self.break_start and self.break_end and self.break_start >= self.break_end:
            raise ValidationError({"break_end": "Intervalo invalido."})
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValidationError({"valid_to": "Periodo de validade invalido."})

    def applies_to(self, date) -> bool:
        if not self.is_active or date.weekday() != self.weekday:
            return False
        if self.valid_from and date < self.valid_from:
            return False
        if self.valid_to and date > self.valid_to:
            return False
        return True


class ScheduleBlock(TenantModel):
    """Bloqueio de agenda: feriado, ferias, ausencia ou reserva interna."""

    class Kind(models.TextChoices):
        HOLIDAY = "holiday", "Feriado"
        VACATION = "vacation", "Ferias"
        ABSENCE = "absence", "Ausencia"
        MEETING = "meeting", "Reuniao"
        MAINTENANCE = "maintenance", "Manutencao"
        OTHER = "other", "Outro"

    professional = models.ForeignKey(
        "professionals.Professional",
        verbose_name="profissional",
        on_delete=models.CASCADE,
        related_name="schedule_blocks",
        null=True,
        blank=True,
        help_text="Vazio = bloqueio para toda a clinica.",
    )
    room = models.ForeignKey(
        "clinics.Room",
        verbose_name="sala",
        on_delete=models.CASCADE,
        related_name="schedule_blocks",
        null=True,
        blank=True,
    )
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.ABSENCE)
    start_at = models.DateTimeField("inicio", db_index=True)
    end_at = models.DateTimeField("fim", db_index=True)
    reason = models.CharField("motivo", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "bloqueio de agenda"
        verbose_name_plural = "bloqueios de agenda"
        ordering = ["-start_at"]
        indexes = [models.Index(fields=["clinic", "start_at", "end_at"])]

    def __str__(self) -> str:
        alvo = self.professional.display_name if self.professional else "Clinica"
        return f"{self.get_kind_display()} - {alvo}"

    def clean(self):
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValidationError({"end_at": "O fim deve ser posterior ao inicio."})


class AppointmentQuerySet(TenantQuerySet):
    """QuerySet de agendamentos -- herda o isolamento por clinica."""

    def active(self):
        return self.exclude(status__in=[Appointment.Status.CANCELED, Appointment.Status.NO_SHOW])

    def in_period(self, start, end):
        return self.filter(start_at__lt=end, end_at__gt=start)

    def today(self):
        now = timezone.localtime()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.filter(start_at__gte=start, start_at__lt=start + timedelta(days=1))


class Appointment(TenantModel):
    """Agendamento de atendimento."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Reservado"
        CONFIRMED = "confirmed", "Confirmado"
        CHECKED_IN = "checked_in", "Aguardando atendimento"
        CALLED = "called", "Chamado"
        IN_PROGRESS = "in_progress", "Em atendimento"
        COMPLETED = "completed", "Concluido"
        CANCELED = "canceled", "Cancelado"
        NO_SHOW = "no_show", "Faltou"

    class Origin(models.TextChoices):
        RECEPTION = "reception", "Recepcao"
        PROFESSIONAL = "professional", "Profissional"
        PORTAL = "portal", "Portal do paciente"
        API = "api", "Integracao"

    patient = models.ForeignKey(
        "patients.Patient",
        verbose_name="paciente",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    professional = models.ForeignKey(
        "professionals.Professional",
        verbose_name="profissional",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    service = models.ForeignKey(
        "clinics.Service",
        verbose_name="servico",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    room = models.ForeignKey(
        "clinics.Room",
        verbose_name="sala",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    insurance = models.ForeignKey(
        "clinics.InsurancePlan",
        verbose_name="convenio",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )

    start_at = models.DateTimeField("inicio", db_index=True)
    end_at = models.DateTimeField("fim")
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.SCHEDULED, db_index=True
    )
    origin = models.CharField(
        "origem", max_length=20, choices=Origin.choices, default=Origin.RECEPTION
    )
    is_overbooking = models.BooleanField("encaixe", default=False)
    price = models.DecimalField("valor", max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField("observacoes", blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    called_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField("motivo do cancelamento", max_length=200, blank=True)
    canceled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reminder_sent_at = models.DateTimeField(null=True, blank=True, editable=False)

    #: Mantem o filtro automatico por tenant e adiciona atalhos de agenda.
    objects = TenantManager.from_queryset(AppointmentQuerySet)()

    class Meta:
        verbose_name = "agendamento"
        verbose_name_plural = "agendamentos"
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["clinic", "start_at"]),
            models.Index(fields=["clinic", "professional", "start_at"]),
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["patient", "-start_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} - {timezone.localtime(self.start_at):%d/%m/%Y %H:%M}"

    # -- regras -------------------------------------------------------------
    def clean(self):
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValidationError({"end_at": "O termino deve ser posterior ao inicio."})

    @property
    def duration_minutes(self) -> int:
        if not self.start_at or not self.end_at:
            return 0
        return int((self.end_at - self.start_at).total_seconds() // 60)

    @property
    def is_active(self) -> bool:
        return self.status not in (self.Status.CANCELED, self.Status.NO_SHOW)

    @property
    def is_past(self) -> bool:
        return bool(self.end_at and self.end_at < timezone.now())

    @property
    def status_color(self) -> str:
        return {
            self.Status.SCHEDULED: "secondary",
            self.Status.CONFIRMED: "primary",
            self.Status.CHECKED_IN: "info",
            self.Status.CALLED: "primary",
            self.Status.IN_PROGRESS: "warning",
            self.Status.COMPLETED: "success",
            self.Status.CANCELED: "danger",
            self.Status.NO_SHOW: "dark",
        }.get(self.status, "secondary")

    @property
    def payment_badge(self) -> dict:
        """
        Indicador visual (emoji + rotulo + classe CSS) do status de pagamento
        do agendamento, usado na agenda. Sempre acompanhado de texto -- nunca
        apenas cor/emoji -- por acessibilidade.
        """
        if not self.clinic.has_module_finance:
            return {}
        receivable = self.receivables.first()
        if receivable is None:
            return {}
        from apps.finance.models import FinancialStatus

        mapping = {
            FinancialStatus.PAID: {"emoji": "\U0001F7E2", "label": "Pago", "css": "success"},
            FinancialStatus.PARTIAL: {"emoji": "\U0001F7E1", "label": "Parcial", "css": "warning"},
            FinancialStatus.PENDING: {"emoji": "\U0001F534", "label": "Pendente", "css": "danger"},
            FinancialStatus.OVERDUE: {"emoji": "\U0001F534", "label": "Vencido", "css": "danger"},
            FinancialStatus.COURTESY: {"emoji": "⚪", "label": "Cortesia", "css": "secondary"},
            FinancialStatus.CANCELED: {"emoji": "⚫", "label": "Cancelado", "css": "dark"},
            FinancialStatus.REFUNDED: {"emoji": "⚫", "label": "Estornado", "css": "dark"},
        }
        return mapping.get(receivable.status, {})

    def can_transition_to(self, status: str) -> bool:
        allowed = {
            self.Status.SCHEDULED: {
                self.Status.CONFIRMED,
                self.Status.CHECKED_IN,
                self.Status.CANCELED,
                self.Status.NO_SHOW,
            },
            self.Status.CONFIRMED: {
                self.Status.CHECKED_IN,
                self.Status.IN_PROGRESS,
                self.Status.CANCELED,
                self.Status.NO_SHOW,
            },
            self.Status.CHECKED_IN: {
                self.Status.CALLED,
                self.Status.IN_PROGRESS,
                self.Status.CANCELED,
                self.Status.NO_SHOW,
            },
            self.Status.CALLED: {
                self.Status.IN_PROGRESS,
                self.Status.CHECKED_IN,
                self.Status.CANCELED,
                self.Status.NO_SHOW,
            },
            self.Status.IN_PROGRESS: {self.Status.COMPLETED, self.Status.CANCELED},
            self.Status.COMPLETED: set(),
            self.Status.CANCELED: {self.Status.SCHEDULED},
            self.Status.NO_SHOW: {self.Status.SCHEDULED},
        }
        return status in allowed.get(self.status, set())


class WaitingListEntry(TenantModel):
    """Lista de espera por vagas na agenda."""

    class Status(models.TextChoices):
        WAITING = "waiting", "Aguardando"
        CONTACTED = "contacted", "Contatado"
        SCHEDULED = "scheduled", "Agendado"
        CANCELED = "canceled", "Cancelado"

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="waiting_entries"
    )
    professional = models.ForeignKey(
        "professionals.Professional",
        on_delete=models.CASCADE,
        related_name="waiting_entries",
        null=True,
        blank=True,
    )
    service = models.ForeignKey(
        "clinics.Service", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    preferred_period = models.CharField(
        "periodo preferido",
        max_length=20,
        choices=[("any", "Qualquer"), ("morning", "Manha"), ("afternoon", "Tarde")],
        default="any",
    )
    priority = models.CharField(
        "prioridade", max_length=10, choices=Priority.choices, default=Priority.NORMAL
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.WAITING, db_index=True
    )
    notes = models.CharField("observacoes", max_length=250, blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "lista de espera"
        verbose_name_plural = "lista de espera"
        ordering = ["-priority", "created_at"]

    def __str__(self) -> str:
        return f"{self.patient} ({self.get_priority_display()})"
