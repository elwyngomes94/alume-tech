"""Tarefas assincronas de notificacao (Celery)."""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger("jja.security")


@shared_task(name="apps.notifications.tasks.processar_fila_de_envio")
def processar_fila_de_envio(limit: int = 100) -> int:
    """
    Processa a fila de envios pendentes.

    E-mail ja e enviado de fato. WhatsApp/SMS/Push ficam marcados como
    ``skipped`` ate que o provedor seja configurado -- a arquitetura esta
    pronta, bastando implementar o cliente do provedor escolhido.
    """
    from apps.core.tenancy import unscoped
    from apps.notifications.models import NotificationDelivery

    processed = 0
    with unscoped("tarefa de envio de notificacoes"):
        pending = NotificationDelivery.objects.filter(
            status=NotificationDelivery.Status.PENDING
        ).order_by("created_at")[:limit]
        for delivery in pending:
            if delivery.scheduled_for and delivery.scheduled_for > timezone.now():
                continue
            delivery.attempts += 1
            try:
                if delivery.channel == NotificationDelivery.Channel.EMAIL:
                    send_mail(
                        delivery.subject or "Notificacao",
                        delivery.body,
                        settings.DEFAULT_FROM_EMAIL,
                        [delivery.destination],
                        fail_silently=False,
                    )
                    delivery.status = NotificationDelivery.Status.SENT
                    delivery.sent_at = timezone.now()
                elif delivery.channel == NotificationDelivery.Channel.PUSH:
                    # Rede de seguranca: o push do "chamar" ja e enviado na
                    # hora (apps.notifications.push.dispatch_ticket_push).
                    # So chega aqui se aquele envio imediato falhou antes de
                    # marcar o status (ex.: processo reiniciado no meio).
                    from apps.calling.models import PushSubscription
                    from apps.notifications.push import send_push

                    subscription = PushSubscription.all_objects.filter(
                        pk=delivery.destination
                    ).first()
                    if subscription is None:
                        delivery.status = NotificationDelivery.Status.SKIPPED
                        delivery.error_message = "Inscricao de push nao encontrada."
                    else:
                        sent, error = send_push(
                            subscription, title=delivery.subject, body=delivery.body
                        )
                        delivery.status = (
                            NotificationDelivery.Status.SENT
                            if sent
                            else NotificationDelivery.Status.FAILED
                        )
                        delivery.error_message = error
                        if sent:
                            delivery.sent_at = timezone.now()
                else:
                    delivery.status = NotificationDelivery.Status.SKIPPED
                    delivery.error_message = "Provedor nao configurado para este canal."
            except Exception as exc:  # pragma: no cover - depende do provedor
                delivery.status = NotificationDelivery.Status.FAILED
                delivery.error_message = str(exc)[:250]
                logger.warning("falha-envio-notificacao id=%s erro=%s", delivery.pk, exc)
            delivery.save(
                update_fields=["status", "attempts", "sent_at", "error_message", "updated_at"]
            )
            processed += 1
    return processed


@shared_task(name="apps.notifications.tasks.enviar_lembretes_agendamento")
def enviar_lembretes_agendamento() -> int:
    """Enfileira lembretes conforme a antecedencia configurada por clinica."""
    from apps.core.tenancy import unscoped
    from apps.notifications.models import NotificationDelivery, NotificationEvent
    from apps.notifications.services import notify, queue_delivery
    from apps.scheduling.models import Appointment

    total = 0
    with unscoped("tarefa de lembretes de agendamento"):
        now = timezone.now()
        appointments = (
            Appointment.objects.filter(
                status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
                start_at__gt=now,
                reminder_sent_at__isnull=True,
            )
            .select_related("patient", "professional", "clinic", "clinic__settings")
        )
        for appointment in appointments:
            settings_obj = getattr(appointment.clinic, "settings", None)
            hours = settings_obj.reminder_hours_before if settings_obj else 24
            if appointment.start_at - now > timedelta(hours=hours):
                continue
            local_start = timezone.localtime(appointment.start_at)
            message = (
                f"Lembrete: atendimento em {local_start:%d/%m/%Y as %H:%M} com "
                f"{appointment.professional.display_name}."
            )
            if appointment.patient.portal_user_id:
                notify(
                    [appointment.patient.portal_user],
                    title="Lembrete de atendimento",
                    message=message,
                    event=NotificationEvent.APPOINTMENT_REMINDER,
                    clinic=appointment.clinic,
                )
            if appointment.patient.email:
                queue_delivery(
                    clinic=appointment.clinic,
                    channel=NotificationDelivery.Channel.EMAIL,
                    destination=appointment.patient.email,
                    subject=f"Lembrete de atendimento - {appointment.clinic}",
                    body=message,
                )
            Appointment.all_objects.filter(pk=appointment.pk).update(reminder_sent_at=now)
            total += 1
    processar_fila_de_envio.delay() if not settings.CELERY_TASK_ALWAYS_EAGER else \
        processar_fila_de_envio()
    return total


@shared_task(name="apps.notifications.tasks.expurgar_notificacoes_antigas")
def expurgar_notificacoes_antigas(days: int = 180) -> int:
    """Remove notificacoes internas lidas ha mais de N dias."""
    from apps.notifications.models import Notification

    limit = timezone.now() - timedelta(days=days)
    queryset = Notification.all_objects.filter(read_at__isnull=False, read_at__lt=limit)
    total = queryset.count()
    queryset.hard_delete()
    return total
