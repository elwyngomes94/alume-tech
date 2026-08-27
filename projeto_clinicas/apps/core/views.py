"""Views utilitarias: redirecionamento inicial, health check, CEP e erros."""
from __future__ import annotations

import requests
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from apps.core.validators import digits

VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"


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


@login_required
def cep_lookup(request, cep):
    """
    Proxy do ViaCEP: evita CORS no navegador e mantem a chamada externa sob
    controle do servidor (testavel via mock). Retorna campos normalizados
    (``street``/``district``/``city``/``state``) para funcionar com
    qualquer formulario, independente do nome dos campos de endereco.
    """
    clean = digits(cep)
    if len(clean) != 8:
        return JsonResponse({"detail": "CEP invalido. Utilize o formato 00000-000."}, status=400)
    try:
        response = requests.get(VIACEP_URL.format(cep=clean), timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return JsonResponse(
            {"detail": "Nao foi possivel consultar o CEP. Preencha o endereco manualmente."},
            status=503,
        )
    if data.get("erro"):
        return JsonResponse(
            {"detail": "CEP nao encontrado. Verifique o numero informado."}, status=404
        )
    return JsonResponse(
        {
            "street": data.get("logradouro", ""),
            "district": data.get("bairro", ""),
            "city": data.get("localidade", ""),
            "state": data.get("uf", ""),
        }
    )


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
