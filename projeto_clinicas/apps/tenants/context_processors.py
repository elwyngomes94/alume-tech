"""Disponibiliza a clinica ativa e as permissoes do usuario nos templates."""
from __future__ import annotations


class PermissionProxy:
    """
    Permite escrever ``{% if perms_clinic.patient_add %}`` nos templates.

    O ponto do codename e substituido por underscore por limitacao da
    linguagem de templates do Django.
    """

    def __init__(self, permissions):
        self._permissions = set(permissions or ())

    def __contains__(self, item) -> bool:
        return item in self._permissions

    def __iter__(self):
        return iter(sorted(self._permissions))

    def __getitem__(self, item) -> bool:
        return item.replace("_", ".", 1) in self._permissions or item in self._permissions

    def __bool__(self) -> bool:
        return bool(self._permissions)


def tenant_context(request):
    user = getattr(request, "user", None)
    clinic = getattr(request, "clinic", None)
    available = []
    if user is not None and user.is_authenticated:
        available = list(user.accessible_clinics()[:50])
    return {
        "active_clinic": clinic,
        "active_membership": getattr(request, "membership", None),
        "available_clinics": available,
        "perms_clinic": PermissionProxy(getattr(request, "clinic_permissions", ())),
    }
