"""Configuracoes usadas pela suite de testes automatizados."""
import tempfile
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["*", "testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "jja-test",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

_tmp = Path(tempfile.mkdtemp(prefix="jja-test-"))
MEDIA_ROOT = _tmp / "media"
PRIVATE_MEDIA_ROOT = _tmp / "private"
BACKUP_ROOT = _tmp / "backups"

CELERY_TASK_ALWAYS_EAGER = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
