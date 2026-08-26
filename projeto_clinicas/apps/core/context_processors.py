"""Variaveis globais de template da plataforma."""
from django.conf import settings


def platform_context(request):
    return {
        "PLATFORM_NAME": settings.PLATFORM_NAME,
        "PLATFORM_PRIMARY_COLOR": settings.PLATFORM_PRIMARY_COLOR,
        "PLATFORM_SUPPORT_EMAIL": settings.PLATFORM_SUPPORT_EMAIL,
        "DEBUG": settings.DEBUG,
    }
