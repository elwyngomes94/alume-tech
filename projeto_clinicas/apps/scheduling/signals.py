"""Signals da agenda: mantem a lista de espera coerente com os agendamentos."""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.scheduling.models import Appointment, WaitingListEntry


@receiver(post_save, sender=Appointment)
def close_waiting_entry(sender, instance: Appointment, created, **kwargs):
    """Ao agendar um paciente que estava na fila, encerra a entrada da fila."""
    if not created:
        return
    WaitingListEntry.all_objects.filter(
        clinic_id=instance.clinic_id,
        patient_id=instance.patient_id,
        status=WaitingListEntry.Status.WAITING,
        is_deleted=False,
    ).update(status=WaitingListEntry.Status.SCHEDULED, appointment=instance)
