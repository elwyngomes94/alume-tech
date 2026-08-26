"""Configuracoes de producao (HTTPS obrigatorio)."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# HTTPS / transporte seguro
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Sessoes em cache + banco para expiracao rapida e revogacao imediata
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

if SENTRY_DSN:  # noqa: F405 - integracao opcional de monitoramento
    try:  # pragma: no cover - depende de dependencia opcional
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,  # noqa: F405
            integrations=[DjangoIntegration()],
            traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
            send_default_pii=False,  # LGPD: nao enviar dados pessoais ao monitoramento
        )
    except ImportError:
        pass
