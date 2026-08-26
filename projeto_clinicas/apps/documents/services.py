"""Regras de acesso a documentos."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from apps.accounts.permissions import Roles
from apps.documents.models import Document, DocumentAccessLog

_signer = TimestampSigner(salt="jja.documents.download")


def can_access_document(user, clinic, document: Document) -> bool:
    """
    Autorizacao de leitura de um documento.

    Ordem de verificacao: tenant -> perfil -> vinculo assistencial.
    """
    if document.clinic_id != getattr(clinic, "pk", None):
        return False
    if user.is_superadmin:
        return True

    # Paciente: apenas os proprios documentos liberados no portal.
    if user.is_patient:
        patient = getattr(user, "patient_profile", None)
        return bool(
            patient
            and document.patient_id == patient.pk
            and document.visible_to_patient
        )

    if not user.has_clinic_perm("document.view", clinic):
        return False

    role = user.role_in(clinic)
    if role == Roles.CLINIC_ADMIN:
        return True

    # Recepcao nao acessa documento clinico.
    is_clinical = document.is_sensitive or (
        document.category.is_clinical if document.category else True
    )
    if role == Roles.RECEPTIONIST:
        return not is_clinical

    if role == Roles.PROFESSIONAL:
        if document.patient_id is None:
            return True
        from apps.medical_records.services import can_access_patient_record

        return can_access_patient_record(user, clinic, document.patient)

    return False


def assert_can_access_document(user, clinic, document: Document) -> None:
    if not can_access_document(user, clinic, document):
        raise PermissionDenied("Voce nao tem permissao para acessar este documento.")


def register_access(document: Document, user, ip: str = "", action: str = "download") -> None:
    DocumentAccessLog.objects.create(
        clinic_id=document.clinic_id,
        document=document,
        user=user if getattr(user, "pk", None) else None,
        ip_address=ip[:45],
        action=action,
    )
    Document.all_objects.filter(pk=document.pk).update(
        download_count=document.download_count + 1
    )


def build_temporary_link(document: Document) -> str:
    """Assina o id do documento para links temporarios (validade curta)."""
    return _signer.sign(str(document.pk))


def resolve_temporary_link(token: str, max_age_seconds: int = 600) -> str:
    try:
        return _signer.unsign(token, max_age=max_age_seconds)
    except SignatureExpired as exc:
        raise PermissionDenied("Link expirado.") from exc
    except BadSignature as exc:
        raise PermissionDenied("Link invalido.") from exc
