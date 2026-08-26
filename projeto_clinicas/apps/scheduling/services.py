"""
Regras de negocio da agenda.

Toda a validacao (conflito de horario, bloqueios, disponibilidade e transicao
de status) vive aqui -- as views apenas orquestram. Isso mantem a regra unica
para o painel web, a API e as tarefas assincronas.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable, List, Optional

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.scheduling.models import Appointment, ScheduleBlock, ScheduleTemplate

ZERO = Decimal("0.00")


class SchedulingError(ValidationError):
    """Erro de regra de agendamento (conflito, bloqueio, indisponibilidade)."""


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    available: bool
    reason: str = ""
    appointment: Optional[Appointment] = None

    @property
    def label(self) -> str:
        return timezone.localtime(self.start).strftime("%H:%M")


# ---------------------------------------------------------------------------
# Consultas de disponibilidade
# ---------------------------------------------------------------------------
def _aware(day: date, moment: time) -> datetime:
    naive = datetime.combine(day, moment)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def blocks_for(professional, start: datetime, end: datetime) -> Iterable[ScheduleBlock]:
    """Bloqueios do profissional e bloqueios gerais da clinica no periodo."""
    from django.db.models import Q

    return ScheduleBlock.objects.filter(
        Q(professional=professional) | Q(professional__isnull=True),
        start_at__lt=end,
        end_at__gt=start,
    )


def conflicting_appointments(
    professional, start: datetime, end: datetime, exclude_pk=None, room=None
):
    """Agendamentos ativos que se sobrepoem ao intervalo informado."""
    from django.db.models import Q

    queryset = Appointment.objects.active().filter(start_at__lt=end, end_at__gt=start)
    condition = Q(professional=professional)
    if room is not None:
        condition |= Q(room=room)
    queryset = queryset.filter(condition)
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.select_related("patient", "professional")


def day_slots(professional, day: date, service=None) -> List[Slot]:
    """
    Gera os horarios do dia para um profissional.

    Combina a grade semanal (``ScheduleTemplate``), os bloqueios e os
    agendamentos ja existentes.
    """
    templates = [
        template
        for template in ScheduleTemplate.objects.filter(professional=professional, is_active=True)
        if template.applies_to(day)
    ]
    if not templates:
        return []

    day_start = _aware(day, time(0, 0))
    day_end = day_start + timedelta(days=1)
    existing = list(
        Appointment.objects.active()
        .filter(professional=professional, start_at__lt=day_end, end_at__gt=day_start)
        .select_related("patient", "service")
    )
    blocks = list(blocks_for(professional, day_start, day_end))

    duration = None
    if service is not None and service.duration_minutes:
        duration = service.duration_minutes

    slots: List[Slot] = []
    for template in templates:
        step = timedelta(minutes=duration or template.slot_minutes or 30)
        cursor = _aware(day, template.start_time)
        limit = _aware(day, template.end_time)
        break_start = _aware(day, template.break_start) if template.break_start else None
        break_end = _aware(day, template.break_end) if template.break_end else None

        while cursor + step <= limit:
            slot_end = cursor + step
            reason = ""
            appointment = None
            available = True

            if break_start and cursor < break_end and slot_end > break_start:
                available, reason = False, "Intervalo"
            for block in blocks:
                if cursor < block.end_at and slot_end > block.start_at:
                    available, reason = False, block.get_kind_display()
                    break
            for item in existing:
                if cursor < item.end_at and slot_end > item.start_at:
                    available, reason, appointment = False, "Ocupado", item
                    break

            slots.append(Slot(cursor, slot_end, available, reason, appointment))
            cursor = slot_end
    return sorted(slots, key=lambda slot: slot.start)


def available_slots(professional, day: date, service=None) -> List[Slot]:
    now = timezone.now()
    return [slot for slot in day_slots(professional, day, service) if slot.available and slot.start > now]


# ---------------------------------------------------------------------------
# Criacao e alteracao
# ---------------------------------------------------------------------------
def validate_appointment(appointment: Appointment, *, allow_overbooking: bool = False) -> None:
    """Valida conflitos e bloqueios antes de gravar."""
    if appointment.start_at >= appointment.end_at:
        raise SchedulingError({"end_at": "O termino deve ser posterior ao inicio."})

    if appointment.patient.clinic_id != appointment.clinic_id:
        raise PermissionDenied("Paciente pertence a outra clinica.")
    if appointment.professional.clinic_id != appointment.clinic_id:
        raise PermissionDenied("Profissional pertence a outra clinica.")

    blocked = list(
        blocks_for(appointment.professional, appointment.start_at, appointment.end_at)
    )
    if blocked:
        raise SchedulingError(
            f"Horario indisponivel: {blocked[0].get_kind_display()}"
            + (f" ({blocked[0].reason})" if blocked[0].reason else "")
        )

    conflicts = conflicting_appointments(
        appointment.professional,
        appointment.start_at,
        appointment.end_at,
        exclude_pk=appointment.pk,
        room=appointment.room,
    )
    conflict = conflicts.first()
    if conflict is not None and not (allow_overbooking and appointment.is_overbooking):
        raise SchedulingError(
            "Ja existe agendamento neste horario: "
            f"{conflict.patient.display_name} as "
            f"{timezone.localtime(conflict.start_at):%H:%M}."
        )


@transaction.atomic
def create_appointment(
    *,
    clinic,
    patient,
    professional,
    start_at: datetime,
    service=None,
    room=None,
    insurance=None,
    duration_minutes: Optional[int] = None,
    notes: str = "",
    origin: str = Appointment.Origin.RECEPTION,
    created_by=None,
    is_overbooking: bool = False,
    gross_amount: Optional[Decimal] = None,
    discount: Optional[Decimal] = None,
    addition: Optional[Decimal] = None,
    payment_method=None,
    pay_now: bool = False,
    amount_paid_now: Optional[Decimal] = None,
    is_courtesy: bool = False,
) -> Appointment:
    duration = duration_minutes or (
        service.duration_minutes if service else professional.appointment_duration
    )
    price = gross_amount if gross_amount is not None else (service.price if service else None)
    appointment = Appointment(
        clinic=clinic,
        patient=patient,
        professional=professional,
        service=service,
        room=room,
        insurance=insurance or patient.insurance,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=duration or 30),
        notes=notes,
        origin=origin,
        created_by=created_by,
        is_overbooking=is_overbooking,
        price=price,
    )
    validate_appointment(appointment, allow_overbooking=True)
    appointment.save()
    _notify(appointment, "created")
    _create_receivable_for_booking(
        appointment,
        discount=discount,
        addition=addition,
        payment_method=payment_method,
        pay_now=pay_now,
        amount_paid_now=amount_paid_now,
        is_courtesy=is_courtesy,
        user=created_by,
    )
    return appointment


@transaction.atomic
def reschedule(appointment: Appointment, new_start: datetime, *, user=None) -> Appointment:
    duration = appointment.duration_minutes or 30
    appointment.start_at = new_start
    appointment.end_at = new_start + timedelta(minutes=duration)
    appointment.status = Appointment.Status.SCHEDULED
    appointment.confirmed_at = None
    validate_appointment(appointment, allow_overbooking=True)
    appointment.save()
    _notify(appointment, "rescheduled")
    return appointment


@transaction.atomic
def change_status(
    appointment: Appointment, new_status: str, *, user=None, reason: str = "",
    payment_disposition: str = "", refund_amount: Optional[Decimal] = None,
    refund_method=None,
):
    """
    ``payment_disposition`` so se aplica ao cancelar um agendamento cuja
    conta ja tem valor recebido: ``"refund"`` registra um estorno,
    qualquer outro valor (inclusive vazio) mantem o valor recebido como
    esta -- nenhuma transacao nova e criada.
    """
    if appointment.status == new_status:
        return appointment
    if not appointment.can_transition_to(new_status):
        raise SchedulingError(
            f"Transicao invalida: {appointment.get_status_display()} -> "
            f"{dict(Appointment.Status.choices).get(new_status, new_status)}."
        )

    now = timezone.now()
    appointment.status = new_status
    if new_status == Appointment.Status.CONFIRMED:
        appointment.confirmed_at = now
    elif new_status == Appointment.Status.CHECKED_IN:
        appointment.checked_in_at = now
    elif new_status == Appointment.Status.IN_PROGRESS:
        appointment.started_at = now
    elif new_status == Appointment.Status.COMPLETED:
        appointment.finished_at = now
    elif new_status == Appointment.Status.CANCELED:
        appointment.canceled_at = now
        appointment.cancel_reason = reason[:200]
        appointment.canceled_by = user
    appointment.save()
    _notify(appointment, new_status)
    if new_status == Appointment.Status.COMPLETED:
        _create_receivable_draft(appointment)
    elif new_status == Appointment.Status.CANCELED:
        _handle_cancellation_finance(
            appointment, user=user, payment_disposition=payment_disposition,
            refund_amount=refund_amount, refund_method=refund_method,
        )
        _offer_waiting_list_slot(appointment)
    return appointment


def _offer_waiting_list_slot(appointment: Appointment) -> None:
    """
    Ao liberar um horario por cancelamento, avisa a recepcao se houver
    alguem compativel na lista de espera. Nunca interrompe o cancelamento
    se a automacao nao estiver habilitada ou algo falhar -- mesmo padrao
    defensivo usado para o financeiro do cancelamento.
    """
    try:
        if not appointment.clinic.has_module("automation"):
            return
        from apps.automation.services.appointment_automation import offer_waiting_list_slot

        offer_waiting_list_slot(appointment)
    except Exception:  # pragma: no cover - nunca bloqueia o cancelamento
        import logging

        logging.getLogger("jja.security").exception(
            "Falha ao oferecer vaga da lista de espera para o agendamento %s", appointment.pk
        )


def _handle_cancellation_finance(
    appointment: Appointment, *, user=None, payment_disposition: str = "",
    refund_amount: Optional[Decimal] = None, refund_method=None,
) -> None:
    """
    Ao cancelar um agendamento com conta financeira ligada: sem pagamento
    recebido, apenas cancela a conta; com pagamento recebido e disposicao
    "refund", registra o estorno; em qualquer outro caso, mantem o valor
    recebido como esta (nenhuma transacao nova, historico preservado).
    """
    try:
        if not appointment.clinic.has_module_finance:
            return
        from apps.finance import services as finance_services
        from apps.finance.models import FinancialStatus, ReceivableAccount

        receivable = ReceivableAccount.objects.filter(appointment=appointment).first()
        if receivable is None or receivable.status == FinancialStatus.CANCELED:
            return
        if receivable.paid_amount <= ZERO:
            finance_services.cancel_receivable(receivable, reason="Agendamento cancelado")
            return
        if payment_disposition == "refund":
            amount = refund_amount if refund_amount is not None else receivable.paid_amount
            method = refund_method or receivable.expected_payment_method
            if amount and amount > ZERO and method is not None:
                finance_services.refund_receivable_payment(
                    receivable, amount=amount, method=method, user=user,
                    reason="Agendamento cancelado",
                )
    except Exception:  # pragma: no cover - nunca bloqueia o cancelamento
        import logging

        logging.getLogger("jja.security").exception(
            "Falha ao tratar financeiro do cancelamento do agendamento %s", appointment.pk
        )


def _create_receivable_for_booking(
    appointment: Appointment, *, discount=None, addition=None, payment_method=None,
    pay_now: bool = False, amount_paid_now=None, is_courtesy: bool = False, user=None,
) -> None:
    """
    Cria a conta a receber no momento do agendamento -- nao mais so na
    conclusao -- quando o financeiro esta habilitado e ha valor definido
    (de tabela de servico ou informado manualmente). Nunca interrompe o
    fluxo da agenda se o financeiro nao estiver habilitado ou algo falhar,
    mesmo padrao defensivo usado para notificacoes.
    """
    try:
        if not appointment.clinic.has_module_finance:
            return
        if appointment.price is None and not is_courtesy:
            return
        from apps.finance.models import FinancialCategory, FinancialStatus, ReceivableAccount
        from apps.finance.services import register_receivable_payment

        if ReceivableAccount.objects.filter(appointment=appointment).exists():
            return
        category = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.INCOME, is_active=True
        ).first()
        if category is None:
            return
        service_date = timezone.localtime(appointment.start_at).date()
        receivable = ReceivableAccount.objects.create(
            clinic=appointment.clinic,
            patient=appointment.patient,
            professional=appointment.professional,
            service=appointment.service,
            appointment=appointment,
            category=category,
            description=f"Atendimento {appointment.patient.display_name}",
            service_date=service_date,
            due_date=service_date,
            gross_amount=appointment.price or ZERO,
            discount=discount or ZERO,
            addition=addition or ZERO,
            expected_payment_method=payment_method,
            status=FinancialStatus.COURTESY if is_courtesy else FinancialStatus.PENDING,
        )
        if is_courtesy:
            return
        if pay_now and payment_method is not None:
            amount = amount_paid_now if amount_paid_now is not None else receivable.net_amount
            if amount and amount > ZERO:
                register_receivable_payment(
                    receivable, amount=amount, method=payment_method, user=user,
                )
    except Exception:  # pragma: no cover - nunca bloqueia a criacao do agendamento
        import logging

        logging.getLogger("jja.security").exception(
            "Falha ao gerar conta a receber do agendamento %s", appointment.pk
        )


def _create_receivable_draft(appointment: Appointment) -> None:
    """
    Rede de seguranca: se por algum motivo o agendamento nao gerou conta a
    receber no momento da criacao (financeiro habilitado depois, por
    exemplo), gera uma ao concluir o atendimento. Idempotente.
    """
    try:
        if not appointment.clinic.has_module_finance:
            return
        if not appointment.service_id or not appointment.service.price:
            return
        from apps.finance.models import FinancialCategory, ReceivableAccount

        if ReceivableAccount.objects.filter(appointment=appointment).exists():
            return
        category = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.INCOME, is_active=True
        ).first()
        if category is None:
            return
        ReceivableAccount.objects.create(
            clinic=appointment.clinic,
            patient=appointment.patient,
            professional=appointment.professional,
            service=appointment.service,
            appointment=appointment,
            category=category,
            description=f"Atendimento {appointment.patient.display_name}",
            service_date=timezone.localtime(appointment.start_at).date(),
            due_date=timezone.localdate(),
            gross_amount=appointment.service.price,
        )
    except Exception:  # pragma: no cover - nunca bloqueia a conclusao do atendimento
        import logging

        logging.getLogger("jja.security").exception(
            "Falha ao gerar conta a receber automatica do agendamento %s", appointment.pk
        )


def _notify(appointment: Appointment, event: str) -> None:
    """Dispara notificacao interna (e-mail/WhatsApp ficam a cargo do Celery)."""
    from apps.notifications.services import notify_appointment_event

    try:
        notify_appointment_event(appointment, event)
    except Exception:  # pragma: no cover - notificacao nunca quebra a agenda
        import logging

        logging.getLogger("jja.security").exception("Falha ao notificar agendamento")


def agenda_summary(clinic, day: Optional[date] = None) -> dict:
    """Indicadores rapidos do dia para o dashboard."""
    day = day or timezone.localdate()
    start = _aware(day, time(0, 0))
    end = start + timedelta(days=1)
    queryset = Appointment.objects.filter(start_at__gte=start, start_at__lt=end)
    return {
        "total": queryset.count(),
        "confirmed": queryset.filter(status=Appointment.Status.CONFIRMED).count(),
        "waiting": queryset.filter(status=Appointment.Status.CHECKED_IN).count(),
        "completed": queryset.filter(status=Appointment.Status.COMPLETED).count(),
        "canceled": queryset.filter(status=Appointment.Status.CANCELED).count(),
        "no_show": queryset.filter(status=Appointment.Status.NO_SHOW).count(),
    }
