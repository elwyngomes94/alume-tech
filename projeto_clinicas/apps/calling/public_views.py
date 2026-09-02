"""
Pagina publica do paciente (sem login).

Segue o mesmo padrao ja usado em ``apps.portal.views.PortalBaseMixin``: a
consulta acontece com o filtro de tenant desativado
(``apps.core.tenancy.unscoped``) e o tenant correto e ativado manualmente
so durante a view, a partir do proprio registro encontrado -- nunca a
partir de um id vindo da URL.
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.calling.models import CallTicket
from apps.core.tenancy import tenant_context, unscoped


class TicketPublicMixin:
    """Resolve a senha pelo token e ativa o tenant so durante a requisicao."""

    def dispatch(self, request, token, *args, **kwargs):
        with unscoped("acesso publico por token de chamada"):
            ticket = (
                CallTicket.objects.filter(
                    access_token=token,
                    token_expires_at__gt=timezone.now(),
                )
                .select_related("clinic", "appointment", "appointment__patient", "appointment__professional", "appointment__room")
                .first()
            )
        if ticket is None or not ticket.clinic.has_module("patient_calling"):
            raise Http404
        self.ticket = ticket
        with tenant_context(ticket.clinic):
            return super().dispatch(request, token, *args, **kwargs)


class PatientTicketView(TicketPublicMixin, View):
    def get(self, request, token):
        appointment = self.ticket.appointment
        context = {
            "ticket": self.ticket,
            "appointment": appointment,
            "vapid_public_key": _vapid_public_key(),
        }
        return render(request, "calling/ticket_page.html", context)


class PatientTicketStatusView(TicketPublicMixin, View):
    def get(self, request, token):
        appointment = self.ticket.appointment
        return JsonResponse(
            {
                "status": appointment.status,
                "status_label": appointment.get_status_display(),
                "room": appointment.room.name if appointment.room_id else "",
                "professional": appointment.professional.display_name,
                "ticket_number": self.ticket.ticket_number,
                "e_sua_vez": appointment.status == appointment.Status.CALLED,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class PatientPushSubscribeView(TicketPublicMixin, View):
    """
    Recebe a inscricao de Web Push criada pelo navegador do paciente.

    Isento de CSRF: a pagina e publica (sem sessao autenticada, portanto
    sem cookie de CSRF do Django) -- a protecao aqui e o proprio token
    opaco e de vida curta na URL, ja validado por ``TicketPublicMixin``.
    """

    def post(self, request, token):
        try:
            payload = json.loads(request.body.decode("utf-8"))
            endpoint = payload["endpoint"]
            keys = payload["keys"]
            p256dh = keys["p256dh"]
            auth = keys["auth"]
        except (KeyError, ValueError, UnicodeDecodeError):
            return JsonResponse({"ok": False}, status=400)

        from apps.calling.services import register_push_subscription

        register_push_subscription(
            self.ticket,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return JsonResponse({"ok": True})


def _vapid_public_key() -> str:
    from django.conf import settings

    return settings.VAPID_PUBLIC_KEY


class ServiceWorkerView(View):
    """
    Serve o service worker do push a partir de ``/chamada/sw-push.js``.

    Um service worker so pode controlar (escopo) o caminho igual ou abaixo
    de onde ele proprio foi servido -- servi-lo direto de ``/static/js/``
    limitaria o escopo a ``/static/js/``, nao a ``/chamada/``. Servir aqui
    evita ter que configurar cabecalhos extras no Whitenoise.
    """

    def get(self, request):
        from django.contrib.staticfiles.finders import find
        from django.http import HttpResponse

        path = find("js/sw-push.js")
        if not path:
            raise Http404
        with open(path, "rb") as handle:
            content = handle.read()
        return HttpResponse(content, content_type="application/javascript")
