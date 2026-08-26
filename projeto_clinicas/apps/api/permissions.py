"""Permissoes da API."""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.audit.services import log_denied


class HasClinicContext(BasePermission):
    """Exige uma clinica ativa (exceto para endpoints marcados como globais)."""

    message = "Nenhuma clinica ativa para esta requisicao."

    def has_permission(self, request, view):
        if getattr(view, "requires_clinic", True) is False:
            return True
        return getattr(request, "clinic", None) is not None


class ClinicPermission(BasePermission):
    """
    Permissao granular por acao.

    A view declara ``permission_map = {"list": "patient.view", ...}`` ou
    ``required_permission``. Sem permissao -> 403 e registro em auditoria.
    """

    def has_permission(self, request, view):
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            return False
        codename = self._codename_for(request, view)
        if codename is None:
            return True
        allowed = request.user.has_clinic_perm(codename, clinic)
        if not allowed:
            log_denied(f"API: permissao '{codename}' negada em {request.path}", request=request)
        return allowed

    def has_object_permission(self, request, view, obj):
        clinic = getattr(request, "clinic", None)
        obj_clinic_id = getattr(obj, "clinic_id", None)
        if obj_clinic_id is not None and str(obj_clinic_id) != str(getattr(clinic, "pk", "")):
            log_denied("API: tentativa de acesso a objeto de outra clinica", request=request)
            return False
        return True

    @staticmethod
    def _codename_for(request, view):
        mapping = getattr(view, "permission_map", None)
        if mapping:
            action = getattr(view, "action", None)
            if action and action in mapping:
                return mapping[action]
            default_key = "read" if request.method in SAFE_METHODS else "write"
            if default_key in mapping:
                return mapping[default_key]
        return getattr(view, "required_permission", None)


class IsSuperAdmin(BasePermission):
    message = "Recurso restrito a administradores da plataforma."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superadmin)


class IsPatientOwner(BasePermission):
    """Garante que o paciente so acesse os proprios registros no portal."""

    def has_object_permission(self, request, view, obj):
        patient = getattr(request.user, "patient_profile", None)
        if patient is None:
            return False
        target = getattr(obj, "patient_id", None) or getattr(obj, "pk", None)
        return str(target) == str(patient.pk)
