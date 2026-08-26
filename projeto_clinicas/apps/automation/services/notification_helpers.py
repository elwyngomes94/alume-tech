"""Pequenos utilitarios sobre apps.notifications reaproveitados pelas automacoes."""
from __future__ import annotations

from typing import List


def users_with_permission(clinic, codename: str) -> List:
    """Usuarios ativos da clinica que possuem a permissao informada."""
    from apps.tenants.models import ClinicMembership

    memberships = ClinicMembership.objects.filter(
        clinic=clinic, is_active=True
    ).select_related("user", "custom_role")
    return [
        membership.user
        for membership in memberships
        if codename in membership.effective_permissions()
    ]
