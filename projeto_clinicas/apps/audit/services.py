"""Servicos de registro de auditoria."""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.db import transaction

from apps.audit.models import AuditAction, AuditLog, AuditResult
from apps.core.tenancy import get_current_tenant, get_current_user, get_request_meta

logger = logging.getLogger("jja.audit")

#: Modelos cuja simples visualizacao ja e considerada acesso a dado sensivel.
SENSITIVE_MODELS = {
    "patients.Patient",
    "medical_records.MedicalRecord",
    "medical_records.MedicalRecordEntry",
    "medical_records.Prescription",
    "examinations.ExaminationRequest",
    "examinations.ExaminationResult",
    "documents.Document",
    "lgpd.Consent",
}


def _snapshot_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None, "", ""
    return user, getattr(user, "email", "")[:254], getattr(user, "role", "")


def log_action(
    action: str,
    *,
    obj: Any = None,
    description: str = "",
    changes: Optional[dict] = None,
    result: str = AuditResult.SUCCESS,
    user=None,
    clinic=None,
    request=None,
    is_sensitive: Optional[bool] = None,
    object_type: str = "",
    object_id: str = "",
    object_repr: str = "",
) -> Optional[AuditLog]:
    """
    Grava um evento na trilha de auditoria.

    Nunca levanta excecao para o chamador: uma falha de auditoria nao pode
    derrubar a operacao do usuario, mas e registrada no log da aplicacao.
    """
    try:
        meta = get_request_meta()
        if request is not None:
            from apps.core.middleware import client_ip

            meta = {
                "ip_address": client_ip(request),
                "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:400],
                "path": request.path[:255],
                "method": request.method,
                "session_key": getattr(getattr(request, "session", None), "session_key", None),
            }

        user = user or (getattr(request, "user", None) if request else None) or get_current_user()
        user_obj, user_email, user_role = _snapshot_user(user)

        clinic = clinic or (getattr(request, "clinic", None) if request else None)
        if clinic is None:
            clinic = get_current_tenant()
        if clinic is None and obj is not None:
            clinic = getattr(obj, "clinic", None)

        if obj is not None:
            object_type = object_type or obj._meta.label
            object_id = object_id or str(getattr(obj, "pk", ""))
            object_repr = object_repr or str(obj)[:250]

        if is_sensitive is None:
            is_sensitive = object_type in SENSITIVE_MODELS or action in (
                AuditAction.VIEW_SENSITIVE,
                AuditAction.DOWNLOAD,
                AuditAction.EXPORT,
            )

        previous = (
            AuditLog.objects.order_by("-created_at").values_list("checksum", flat=True).first()
            or ""
        )

        entry = AuditLog(
            user=user_obj,
            user_email=user_email,
            user_role=user_role or "",
            clinic=clinic if getattr(clinic, "pk", None) else None,
            clinic_name=(str(clinic) if clinic else "")[:180],
            action=action,
            object_type=object_type[:120],
            object_id=str(object_id)[:64],
            object_repr=(object_repr or "")[:250],
            description=description or "",
            changes=changes or {},
            result=result,
            is_sensitive=bool(is_sensitive),
            ip_address=(meta.get("ip_address") or "")[:45],
            user_agent=(meta.get("user_agent") or "")[:400],
            path=(meta.get("path") or "")[:255],
            method=(meta.get("method") or "")[:10],
            session_key=(meta.get("session_key") or "")[:64],
            previous_checksum=previous,
        )
        with transaction.atomic(savepoint=True):
            entry.save()
        return entry
    except Exception:  # pragma: no cover - auditoria nunca quebra a aplicacao
        logger.exception("Falha ao gravar registro de auditoria (action=%s)", action)
        return None


def log_view(obj, request=None, description: str = "") -> Optional[AuditLog]:
    """Registra a consulta a um dado sensivel (prontuario, paciente, exame)."""
    return log_action(
        AuditAction.VIEW_SENSITIVE,
        obj=obj,
        request=request,
        description=description or f"Consulta a {obj._meta.verbose_name}",
        is_sensitive=True,
    )


def log_denied(description: str, request=None, obj=None) -> Optional[AuditLog]:
    return log_action(
        AuditAction.ACCESS_DENIED,
        obj=obj,
        request=request,
        description=description,
        result=AuditResult.DENIED,
        is_sensitive=True,
    )


def diff_instance(old_values: dict, new_instance, fields=None) -> dict:
    """Compara valores antigos com o estado atual e devolve apenas o que mudou."""
    changes = {}
    tracked = fields or old_values.keys()
    hidden = {"password", "mfa_secret", "key_hash"}
    for field in tracked:
        if field in hidden:
            continue
        before = old_values.get(field)
        after = getattr(new_instance, field, None)
        if str(before) != str(after):
            changes[field] = {"de": _short(before), "para": _short(after)}
    return changes


def _short(value) -> str:
    text = "" if value is None else str(value)
    return text[:200]
