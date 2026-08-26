"""Views utilitarias: redirecionamento inicial, health check e erros."""
from __future__ import annotations

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View


class RootRedirectView(View):
    """Envia cada usuario para o painel correspondente ao seu perfil."""

    def get(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect("accounts:login")
        if user.is_superadmin:
            return redirect("platform:dashboard")
        if user.is_patient:
            return redirect("portal:home")
        return redirect("dashboard:home")


def health_check(request):
    """Endpoint de monitoramento (usado por Docker/Nginx/uptime checks)."""
    database_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # pragma: no cover - indisponibilidade de banco
        database_ok = False
    status = 200 if database_ok else 503
    return JsonResponse({"status": "ok" if database_ok else "degraded", "database": database_ok},
                        status=status)


def handler403(request, exception=None):
    return render(
        request,
        "errors/403.html",
        {"message": str(exception) if exception else ""},
        status=403,
    )


def handler404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def handler500(request):
    return render(request, "errors/500.html", status=500)
