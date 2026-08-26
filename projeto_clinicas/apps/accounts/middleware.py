"""
Middleware de seguranca de sessao.

Responsavel por:

* encerrar sessoes ociosas alem do limite configurado;
* exigir a segunda etapa de autenticacao (MFA) antes de liberar o sistema;
* forcar a troca de senha quando marcada pelo administrador;
* bloquear imediatamente sessoes revogadas em outro dispositivo.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

LAST_ACTIVITY_KEY = "jja_last_activity"
MFA_VERIFIED_KEY = "jja_mfa_verified"

EXEMPT_PATH_PREFIXES = (
    "/accounts/login",
    "/accounts/logout",
    "/accounts/senha",
    "/accounts/mfa",
    "/accounts/trocar-senha",
    "/static/",
    "/media/",
    "/healthz",
)


class SessionSecurityMiddleware(MiddlewareMixin):
    def process_request(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None

        path = request.path
        if path.startswith(EXEMPT_PATH_PREFIXES):
            return None

        # 1. Sessao revogada em outro dispositivo
        from apps.accounts.models import UserSession

        session_key = request.session.session_key
        if session_key:
            revoked = UserSession.objects.filter(
                user=user, session_key=session_key, revoked_at__isnull=False
            ).exists()
            if revoked:
                logout(request)
                messages.warning(request, "Sua sessao foi encerrada em outro dispositivo.")
                return redirect(settings.LOGIN_URL)

        # 2. Inatividade
        last_activity = request.session.get(LAST_ACTIVITY_KEY)
        now = timezone.now().timestamp()
        if last_activity and (now - last_activity) > settings.SESSION_COOKIE_AGE:
            logout(request)
            messages.info(request, "Sessao encerrada por inatividade.")
            return redirect(settings.LOGIN_URL)
        request.session[LAST_ACTIVITY_KEY] = now

        # 3. Segunda etapa de autenticacao
        if user.mfa_enabled and not request.session.get(MFA_VERIFIED_KEY):
            return redirect(reverse("accounts:mfa-verify"))

        # 4. Troca de senha obrigatoria
        if user.must_change_password:
            messages.warning(request, "Por seguranca, defina uma nova senha para continuar.")
            return redirect(reverse("accounts:password-change"))

        return None
