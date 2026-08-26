"""Validadores compartilhados: documentos brasileiros e uploads."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible

# ---------------------------------------------------------------------------
# Documentos brasileiros
# ---------------------------------------------------------------------------
_ONLY_DIGITS = re.compile(r"\D")


def digits(value: str) -> str:
    return _ONLY_DIGITS.sub("", value or "")


def validate_cpf(value: str) -> None:
    cpf = digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ValidationError("CPF invalido.")
    for length in (9, 10):
        total = sum(int(cpf[i]) * ((length + 1) - i) for i in range(length))
        check = (total * 10) % 11
        check = 0 if check == 10 else check
        if check != int(cpf[length]):
            raise ValidationError("CPF invalido.")


def validate_cnpj(value: str) -> None:
    cnpj = digits(value)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        raise ValidationError("CNPJ invalido.")
    weights_first = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_second = [6] + weights_first
    for weights, position in ((weights_first, 12), (weights_second, 13)):
        total = sum(int(cnpj[i]) * weights[i] for i in range(position))
        check = total % 11
        check = 0 if check < 2 else 11 - check
        if check != int(cnpj[position]):
            raise ValidationError("CNPJ invalido.")


def validate_cpf_or_cnpj(value: str) -> None:
    document = digits(value)
    if len(document) == 11:
        validate_cpf(value)
    elif len(document) == 14:
        validate_cnpj(value)
    else:
        raise ValidationError("Informe um CPF (11 digitos) ou CNPJ (14 digitos) valido.")


def validate_cep(value: str) -> None:
    if len(digits(value)) != 8:
        raise ValidationError("CEP invalido. Utilize o formato 00000-000.")


def validate_phone(value: str) -> None:
    number = digits(value)
    if not 10 <= len(number) <= 13:
        raise ValidationError("Telefone invalido. Informe DDD e numero.")


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
#: Assinaturas (magic numbers) aceitas, por extensao.
_MAGIC_SIGNATURES = {
    "pdf": [b"%PDF-"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "webp": [b"RIFF"],
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "odt": [b"PK\x03\x04"],
    "doc": [b"\xd0\xcf\x11\xe0"],
    "xls": [b"\xd0\xcf\x11\xe0"],
}


@deconstructible
class UploadValidator:
    """
    Valida extensao, tipo MIME, assinatura binaria e tamanho do arquivo.

    Nao confiamos no ``content_type`` enviado pelo navegador: ele e apenas um
    dos criterios; a assinatura binaria do arquivo tambem e conferida.
    """

    def __init__(self, allowed_extensions=None, allowed_mime_types=None, max_size=None):
        self.allowed_extensions = [
            ext.lower() for ext in (allowed_extensions or settings.ALLOWED_UPLOAD_EXTENSIONS)
        ]
        self.allowed_mime_types = allowed_mime_types or settings.ALLOWED_UPLOAD_MIME_TYPES
        self.max_size = max_size or settings.MAX_UPLOAD_SIZE

    def __call__(self, file_obj):
        name = getattr(file_obj, "name", "") or ""
        extension = Path(name).suffix.lower().lstrip(".")

        if extension not in self.allowed_extensions:
            raise ValidationError(
                "Extensao '%(ext)s' nao permitida. Permitidas: %(allowed)s.",
                params={"ext": extension or "?", "allowed": ", ".join(self.allowed_extensions)},
            )

        size = getattr(file_obj, "size", 0) or 0
        if size > self.max_size:
            raise ValidationError(
                "Arquivo muito grande (%(size).1f MB). Limite: %(max).1f MB.",
                params={"size": size / 1048576, "max": self.max_size / 1048576},
            )
        if size == 0:
            raise ValidationError("Arquivo vazio.")

        content_type = getattr(file_obj, "content_type", None) or mimetypes.guess_type(name)[0]
        if content_type and content_type not in self.allowed_mime_types:
            raise ValidationError(
                "Tipo de arquivo nao permitido (%(mime)s).", params={"mime": content_type}
            )

        self._validate_signature(file_obj, extension)

    def _validate_signature(self, file_obj, extension: str) -> None:
        signatures = _MAGIC_SIGNATURES.get(extension)
        if not signatures:
            return
        try:
            position = file_obj.tell()
            file_obj.seek(0)
            header = file_obj.read(16)
            file_obj.seek(position)
        except (AttributeError, OSError):  # pragma: no cover - arquivos ja fechados
            return
        if isinstance(header, str):  # pragma: no cover
            header = header.encode("latin-1", "ignore")
        if not any(header.startswith(sig) for sig in signatures):
            raise ValidationError(
                "O conteudo do arquivo nao corresponde a extensao informada. "
                "Envio bloqueado por seguranca."
            )

    def __eq__(self, other):
        return (
            isinstance(other, UploadValidator)
            and self.allowed_extensions == other.allowed_extensions
            and self.max_size == other.max_size
        )


validate_upload = UploadValidator()
validate_image_upload = UploadValidator(
    allowed_extensions=["jpg", "jpeg", "png", "webp"],
    allowed_mime_types=["image/jpeg", "image/png", "image/webp"],
    max_size=8 * 1024 * 1024,
)


def validate_hex_color(value: str) -> None:
    if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value or ""):
        raise ValidationError("Informe uma cor no formato hexadecimal, ex: #0b5ed7.")
