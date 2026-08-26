"""Configuracoes de desenvolvimento local."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

# Em desenvolvimento nao exigimos Redis instalado.
if not env("REDIS_URL", default="").startswith("redis://") or env.bool(
    "USE_LOCMEM_CACHE", default=True
):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "jja-dev",
        }
    }

CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=True)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
