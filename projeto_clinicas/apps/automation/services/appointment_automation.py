"""Automacoes operacionais da agenda (Fase 1 -- lista de espera automatica)."""
from __future__ import annotations

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.automation.services import engine
from apps.automation.services.notification_helpers import users_with_permission
from apps.scheduling.models import WaitingListEntry


def offer_waiting_list_slot(appointment) -> None:
    """
    Quando um agendamento e cancelado, verifica se ha alguem compativel na
    lista de espera e, se houver, avisa a recepcao para entrar em contato.

    Nao agenda automaticamente: a recepcao confirma com o paciente e
    registra o aceite/recusa na tela de lista de espera ja existente
    (``WaitingListUpdateStatusView``).
    """
    clinic = appointment.clinic

    def condition() -> bool:
        if not engine.get_settings(clinic).waiting_list_auto_invite:
            return False
        return _matching_entry(appointment) is not None

    def action() -> dict:
        entry = _matching_entry(appointment)
        entry.status = WaitingListEntry.Status.CONTACTED
        entry.contacted_at = timezone.now()
        entry.save(update_fields=["status", "contacted_at", "updated_at"])

        from apps.notifications.models import NotificationEvent
        from apps.notifications.services import notify

        recipients = users_with_permission(clinic, "appointment.change")
        notify(
            recipients,
            title="Horario liberado na lista de espera",
            message=(
                f"{entry.patient.display_name} esta aguardando um horario com "
                f"{appointment.professional.display_name}. Um horario acabou de ser liberado."
            ),
            event=NotificationEvent.MESSAGE,
            clinic=clinic,
            url=reverse("scheduling:waiting-list"),
            level="info",
        )
        return {"waiting_list_entry_id": str(entry.pk)}

    engine.run(
        "waiting_list_invite",
        clinic,
        idempotency_key=f"appointment:{appointment.pk}",
        action=action,
        condition=condition,
        trigger_object=appointment,
    )


def _matching_entry(appointment):
    return (
        WaitingListEntry.objects.filter(
            professional=appointment.professional, status=WaitingListEntry.Status.WAITING,
        )
        .filter(Q(service=appointment.service) | Q(service__isnull=True))
        .first()
    )
