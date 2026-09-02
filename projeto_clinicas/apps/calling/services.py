"""Regras de negocio da fila de chamada de pacientes."""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.calling.models import CallEvent, CallPanelConfig, CallTicket, PushSubscription

#: tempo de vida do token publico da senha -- generoso o suficiente para
#: cobrir um dia de atendimento com atraso, sem ficar valido indefinidamente.
TOKEN_TTL_HOURS = 14


def get_or_create_config(clinic) -> CallPanelConfig:
    config, _ = CallPanelConfig.objects.get_or_create(clinic=clinic)
    return config


@transaction.atomic
def create_ticket_for_checkin(appointment, *, priority: str = CallTicket.Priority.NORMAL) -> Optional[CallTicket]:
    """
    Gera a senha do dia para um agendamento que acabou de dar entrada
    (status CHECKED_IN). Idempotente: se ja existir uma senha para este
    agendamento, apenas a devolve.

    Numeracao concorrente-segura: mesmo padrao ja usado para agendamentos
    (``apps.scheduling.services.create_appointment``) -- trava a linha da
    clinica antes de contar as senhas do dia.
    """
    existing = getattr(appointment, "call_ticket", None)
    if existing is not None:
        return existing

    from apps.clinics.models import Clinic

    clinic = Clinic.objects.select_for_update().get(pk=appointment.clinic_id)
    if not clinic.has_module("patient_calling"):
        return None

    config = get_or_create_config(clinic)
    today = timezone.localdate()
    count_today = CallTicket.objects.filter(clinic=clinic, created_at__date=today).count()
    ticket_number = f"{config.ticket_prefix}{count_today + 1:03d}"

    ticket = CallTicket.objects.create(
        appointment=appointment,
        ticket_number=ticket_number,
        priority=priority,
        access_token=secrets.token_urlsafe(32),
        token_expires_at=timezone.now() + timedelta(hours=TOKEN_TTL_HOURS),
    )
    return ticket


def register_call(appointment, *, user=None) -> None:
    """Registra a 1a chamada (transicao para CALLED) -- soma ao contador."""
    ticket = getattr(appointment, "call_ticket", None)
    if ticket is None:
        return
    ticket.call_count += 1
    ticket.save(update_fields=["call_count"])
    CallEvent.objects.create(ticket=ticket, kind=CallEvent.Kind.CALLED, created_by=user)


def recall(ticket: CallTicket, *, user=None) -> None:
    """'Rechamar': nao muda o status do agendamento, so reforca o aviso."""
    ticket.call_count += 1
    ticket.save(update_fields=["call_count"])
    CallEvent.objects.create(ticket=ticket, kind=CallEvent.Kind.RECALLED, created_by=user)

    from apps.notifications.services import notify_appointment_event

    notify_appointment_event(ticket.appointment, "called")


def queue_for_clinic(clinic, *, statuses):
    """Senhas do dia da clinica nos status informados, em ordem de prioridade."""
    today = timezone.localdate()
    tickets = list(
        CallTicket.objects.filter(clinic=clinic, created_at__date=today, appointment__status__in=statuses)
        .select_related("appointment", "appointment__patient", "appointment__professional", "appointment__room")
    )
    tickets.sort(key=lambda t: (t.priority_weight, t.appointment.checked_in_at or t.created_at))
    return tickets


def register_push_subscription(ticket: CallTicket, *, endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> PushSubscription:
    subscription, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"ticket": ticket, "p256dh": p256dh, "auth": auth, "user_agent": user_agent[:255]},
    )
    return subscription
