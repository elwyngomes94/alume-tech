"""Managers e querysets base: soft delete + isolamento automatico por tenant."""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.tenancy import get_current_tenant_id, is_unscoped


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet com exclusao logica."""

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def delete(self, user=None):  # type: ignore[override]
        """Exclusao logica em massa (nao remove fisicamente do banco)."""
        return self.update(
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by=user,
            updated_at=timezone.now(),
        )

    def hard_delete(self):
        """Remocao fisica. Use somente em rotinas administrativas conscientes."""
        return super().delete()

    def restore(self):
        return self.update(is_deleted=False, deleted_at=None, deleted_by=None)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager padrao: esconde registros excluidos logicamente."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def with_deleted(self):
        return super().get_queryset()


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager sem nenhum filtro. Usado como ``base_manager`` do Django."""


class TenantQuerySet(SoftDeleteQuerySet):
    def for_clinic(self, clinic):
        clinic_id = getattr(clinic, "pk", clinic)
        return self.filter(clinic_id=clinic_id)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """
    Manager que aplica automaticamente o filtro pela clinica ativa.

    Comportamento:

    * tenant ativo definido  -> ``WHERE clinic_id = <tenant> AND is_deleted = false``
    * contexto global (:func:`apps.core.tenancy.unscoped`) -> sem filtro de tenant
    * sem tenant e sem contexto global -> ``none()`` (falha fechada)

    Isso garante que uma view esquecida ou uma query solta jamais retorne dados
    de outra clinica: na ausencia de contexto o resultado e vazio.
    """

    def get_queryset(self):
        queryset = super().get_queryset().filter(is_deleted=False)
        if is_unscoped():
            return queryset
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return queryset.none()
        return queryset.filter(clinic_id=tenant_id)

    def with_deleted(self):
        queryset = super().get_queryset()
        if is_unscoped():
            return queryset
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return queryset.none()
        return queryset.filter(clinic_id=tenant_id)
