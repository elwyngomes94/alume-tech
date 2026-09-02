"""
Envio de Web Push (VAPID).

Diferente dos demais canais (que ficam na fila e sao processados pelo
Celery beat a cada 30 min, em ``apps.notifications.tasks.
enviar_lembretes_agendamento``), o push de "sua vez chegou" precisa ser
quase instantaneo -- por isso e enviado no mesmo instante em que a fila e
enfileirada (``notify_appointment_event``), nao em lote depois.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("jja.security")


def vapid_configured() -> bool:
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)


def send_push(subscription, *, title: str, body: str, url: str = "") -> tuple[bool, str]:
    """
    Envia uma notificacao push para uma unica inscricao.

    Retorna ``(sucesso, mensagem_de_erro)``. Em caso de 404/410 (inscricao
    invalida/expirada), o chamador deve apagar a inscricao -- o navegador
    nao vai mais aceitar push nela.
    """
    if not vapid_configured():
        return False, "Chaves VAPID nao configuradas."

    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": title, "body": body, "url": url})
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIMS_EMAIL}"},
        )
        return True, ""
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            from apps.calling.models import PushSubscription

            PushSubscription.all_objects.filter(pk=subscription.pk).delete()
        logger.warning("falha-envio-push endpoint=%s erro=%s", subscription.endpoint, exc)
        return False, str(exc)[:250]


def dispatch_ticket_push(ticket, *, title: str, body: str, url: str = "") -> None:
    """Envia (e registra) o push para todas as inscricoes ativas da senha."""
    from apps.notifications.models import NotificationDelivery
    from apps.notifications.services import queue_delivery

    for subscription in ticket.push_subscriptions.all():
        delivery = queue_delivery(
            clinic=ticket.clinic,
            channel=NotificationDelivery.Channel.PUSH,
            destination=str(subscription.pk),
            subject=title,
            body=body,
        )
        if delivery is None:
            continue
        sent, error = send_push(subscription, title=title, body=body, url=url)
        delivery.attempts = 1
        if sent:
            delivery.status = NotificationDelivery.Status.SENT
            delivery.sent_at = timezone.now()
        else:
            delivery.status = NotificationDelivery.Status.FAILED
            delivery.error_message = error
        delivery.save(update_fields=["status", "attempts", "sent_at", "error_message", "updated_at"])
