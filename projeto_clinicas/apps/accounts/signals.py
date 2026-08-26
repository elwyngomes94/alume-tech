"""Signals de conta: rastreio de sessao e alerta de acesso suspeito."""
from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from apps.accounts.services import track_session


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    if request is not None:
        track_session(user, request)


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    """Falhas ja sao registradas no backend; aqui apenas garantimos o log."""
    import logging

    logging.getLogger("jja.security").warning(
        "falha-de-login email=%s", (credentials or {}).get("username", "?")
    )
