"""
Armazenamento privado de arquivos.

Documentos clinicos, exames e fotografias JAMAIS ficam sob ``MEDIA_ROOT``
(diretorio publico). Eles vao para ``PRIVATE_MEDIA_ROOT``, que nao e servido
pelo Nginx/WhiteNoise e so pode ser lido pela view autenticada
``apps.documents.views.DocumentDownloadView``.
"""
from __future__ import annotations

import secrets
import unicodedata
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    """FileSystemStorage apontando para o diretorio privado, sem URL publica."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("location", str(settings.PRIVATE_MEDIA_ROOT))
        kwargs.setdefault("base_url", None)
        kwargs.setdefault("file_permissions_mode", 0o600)
        kwargs.setdefault("directory_permissions_mode", 0o700)
        super().__init__(*args, **kwargs)

    def url(self, name):  # pragma: no cover - protecao explicita
        raise NotImplementedError(
            "Arquivos privados nao possuem URL direta. Use a view de download "
            "autenticada (documents:download)."
        )


private_storage = PrivateMediaStorage()


def sanitize_filename(filename: str) -> str:
    """Remove acentos, caminhos e caracteres perigosos do nome do arquivo."""
    name = Path(filename).name
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._- ").strip()
    safe = safe.replace(" ", "_")
    return safe[:120] or "arquivo"


def private_upload_path(instance, filename: str) -> str:
    """
    Caminho imprevisivel, segmentado por clinica.

    Formato: ``<clinic_id>/<app>/<ano>/<mes>/<token>_<nome_sanitizado>``

    O token aleatorio impede adivinhacao de caminhos mesmo em caso de
    exposicao acidental do diretorio.
    """
    from django.utils import timezone

    clinic_id = getattr(instance, "clinic_id", None) or "plataforma"
    app_label = instance._meta.app_label
    today = timezone.now()
    token = secrets.token_hex(8)
    return f"{clinic_id}/{app_label}/{today:%Y}/{today:%m}/{token}_{sanitize_filename(filename)}"


def clinic_logo_path(instance, filename: str) -> str:
    """Logos sao publicos (identidade visual) e ficam em MEDIA_ROOT."""
    token = secrets.token_hex(4)
    return f"clinics/logos/{instance.pk or 'novo'}/{token}_{sanitize_filename(filename)}"
