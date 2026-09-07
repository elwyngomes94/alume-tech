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


# ---------------------------------------------------------------------------
# App Android (TWA)
# ---------------------------------------------------------------------------
#: Fingerprint SHA-256 do certificado usado para assinar o APK (gerado uma
#: unica vez ao criar o keystore -- ver relato de entrega). Sem isso, o
#: Android nao confia que o app e o site sao do mesmo dono e o TWA abre
#: dentro de uma Custom Tab (com barra de navegador), em vez de tela cheia.
ANDROID_APP_SHA256_FINGERPRINT = (
    "FD:96:63:D9:07:22:8C:4D:9D:B3:B2:4E:95:20:6F:BF:0E:A6:03:1C:B0:EF:14:3B:35:38:15:F2:9F:1C:D4:12"
)
ANDROID_APP_PACKAGE_ID = "com.alumetech.app"


def asset_links_json(request):
    """Digital Asset Links: prova que o app Android e este site sao do mesmo dono."""
    return JsonResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": ANDROID_APP_PACKAGE_ID,
                    "sha256_cert_fingerprints": [ANDROID_APP_SHA256_FINGERPRINT],
                },
            }
        ],
        safe=False,
    )


def download_android_app(request):
    """Baixa o APK do aplicativo Android (fora da Play Store, direto do sistema)."""
    from pathlib import Path

    from django.conf import settings
    from django.http import FileResponse, Http404

    apk_path = Path(settings.BASE_DIR) / "static" / "downloads" / "alume-tech.apk"
    if not apk_path.exists():
        raise Http404
    return FileResponse(
        open(apk_path, "rb"),
        as_attachment=True,
        filename="alume-tech.apk",
        content_type="application/vnd.android.package-archive",
    )
