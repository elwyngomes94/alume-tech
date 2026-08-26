"""Middlewares gerais: contexto de requisicao e cabecalhos de seguranca."""
from __future__ import annotations

from apps.core.tenancy import (
    clear_current_tenant,
    set_current_user,
    set_request_meta,
)


def client_ip(request) -> str:
    """IP real do cliente considerando proxy reverso confiavel."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


class RequestContextMiddleware:
    """
    Publica usuario, IP e User-Agent no contexto para uso da auditoria.

    Fica antes do middleware de tenant para que qualquer falha ja possa ser
    registrada com a identificacao do solicitante.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        meta = {
            "ip_address": client_ip(request),
            "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:400],
            "path": request.path[:255],
            "method": request.method,
            "session_key": getattr(getattr(request, "session", None), "session_key", None),
        }
        set_request_meta(meta)
        set_current_user(getattr(request, "user", None))
        try:
            response = self.get_response(request)
        finally:
            set_current_user(None)
            set_request_meta({})
            clear_current_tenant()
        return response


class SecurityHeadersMiddleware:
    """Cabecalhos de seguranca adicionais (CSP, permissions policy, no-store)."""

    CSP = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.setdefault("X-Content-Type-Options", "nosniff")
        # Paginas com dados de saude nunca devem ficar em cache do navegador.
        if request.path.startswith(("/app/", "/platform/", "/patient/", "/api/")):
            response.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, private")
            response.setdefault("Pragma", "no-cache")
        return response
