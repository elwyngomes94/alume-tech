"""Servicos de notificacao."""
from __future__ import annotations

from typing import Iterable, Optional

from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationEvent,
)


def notify(
    recipients: Iterable,
    *,
    title: str,
    message: str = "",
    event: str = NotificationEvent.SYSTEM,
    clinic=None,
    url: str = "",
    level: str = "info",
) -> int:
    """Cria notificacoes internas para uma lista de usuarios."""
    created = 0
    seen = set()
    for user in recipients:
        if user is None or not getattr(user, "pk", None) or user.pk in seen:
            continue
        seen.add(user.pk)
        Notification.objects.create(
            recipient=user,
            clinic=clinic,
            event=event,
            title=title[:140],
            message=message,
            url=url[:255],
            level=level,
        )
        created += 1
    return created


def queue_delivery(
    *,
    clinic,
    channel: str,
    destination: str,
    body: str,
    subject: str = "",
    notification: Optional[Notification] = None,
    scheduled_for=None,
) -> Optional[NotificationDelivery]:
    if not destination:
        return None
    return NotificationDelivery.objects.create(
        clinic=clinic,
        notification=notification,
        channel=channel,
        destination=destination[:180],
        subject=subject[:180],
        body=body,
        scheduled_for=scheduled_for,
    )


# ---------------------------------------------------------------------------
# Eventos de dominio
# ---------------------------------------------------------------------------
EVENT_TITLES = {
    "created": ("Novo agendamento", NotificationEvent.APPOINTMENT_CREATED, "info"),
    "rescheduled": ("Agendamento remarcado", NotificationEvent.APPOINTMENT_RESCHEDULED, "warning"),
    "canceled": ("Agendamento cancelado", NotificationEvent.APPOINTMENT_CANCELED, "danger"),
    "confirmed": ("Agendamento confirmado", NotificationEvent.APPOINTMENT_CONFIRMED, "success"),
    "called": ("Paciente chamado", NotificationEvent.APPOINTMENT_CALLED, "info"),
}


def notify_appointment_event(appointment, event: str) -> None:
    """Avisa profissional e paciente sobre mudancas no agendamento."""
    title, event_code, level = EVENT_TITLES.get(
        event, ("Atualizacao de agendamento", NotificationEvent.SYSTEM, "info")
    )
    local_start = timezone.localtime(appointment.start_at)
    message = (
        f"{appointment.patient.display_name} com {appointment.professional.display_name} "
        f"em {local_start:%d/%m/%Y as %H:%M}."
    )
    recipients = []
    if appointment.professional.user_id:
        recipients.append(appointment.professional.user)
    if appointment.patient.portal_user_id:
        recipients.append(appointment.patient.portal_user)

    notify(
        recipients,
        title=title,
        message=message,
        event=event_code,
        clinic=appointment.clinic,
        url=reverse("scheduling:appointment-detail", args=[appointment.pk]),
        level=level,
    )

    settings_obj = getattr(appointment.clinic, "settings", None)
    if settings_obj and settings_obj.notify_email and appointment.patient.email:
        queue_delivery(
            clinic=appointment.clinic,
            channel=NotificationDelivery.Channel.EMAIL,
            destination=appointment.patient.email,
            subject=f"{title} - {appointment.clinic}",
            body=message,
        )
    if settings_obj and settings_obj.notify_whatsapp and appointment.patient.whatsapp:
        queue_delivery(
            clinic=appointment.clinic,
            channel=NotificationDelivery.Channel.WHATSAPP,
            destination=appointment.patient.whatsapp,
            body=f"{title}: {message}",
        )


def notify_examination_result(result) -> None:
    patient = result.request.patient
    if not result.released_to_patient or not patient.portal_user_id:
        return
    notify(
        [patient.portal_user],
        title="Resultado de exame disponivel",
        message=f"O resultado da solicitacao #{result.request.number} esta disponivel.",
        event=NotificationEvent.EXAM_RESULT,
        clinic=result.clinic,
        url=reverse("portal:examinations"),
        level="success",
    )


def notify_document_available(document) -> None:
    patient = document.patient
    if document.visible_to_patient and patient and patient.portal_user_id:
        notify(
            [patient.portal_user],
            title="Novo documento disponivel",
            message=document.title,
            event=NotificationEvent.DOCUMENT_AVAILABLE,
            clinic=document.clinic,
            url=reverse("portal:documents"),
        )


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
