"""Modelos abstratos reutilizados por todo o JJA System."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone

from apps.core.managers import (
    AllObjectsManager,
    SoftDeleteManager,
    TenantManager,
)
from apps.core.tenancy import get_current_tenant_id, get_current_user, is_unscoped


class UUIDModel(models.Model):
    """Chave primaria UUID: identificadores publicos nao sequenciais."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True

    @property
    def is_saved(self) -> bool:
        """
        Indica se o registro ja foi persistido no banco.

        Como o pk usa ``default=uuid.uuid4``, uma instancia recem-criada (e
        ainda nao salva) ja possui um pk preenchido -- por isso
        ``instance.pk`` NAO serve para distinguir "novo" de "existente" (nem
        em Python nem em templates, que bloqueiam atributos com "_"
        iniciais, tornando ``_state.adding`` inacessivel diretamente).
        """
        return not self._state.adding


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("criado em", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Exclusao logica com rastro de quem excluiu e quando."""

    is_deleted = models.BooleanField("excluido", default=False, db_index=True)
    deleted_at = models.DateTimeField("excluido em", null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="excluido por",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, hard: bool = False, user=None):
        """Por padrao executa exclusao logica (LGPD/retencao de dados clinicos)."""
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user or get_current_user()
        if self.deleted_by is not None and not getattr(self.deleted_by, "pk", None):
            self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])
        return (1, {self._meta.label: 1})

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])


class BaseModel(UUIDModel, TimeStampedModel, SoftDeleteModel):
    """Modelo base da plataforma (nao pertence a uma clinica especifica)."""

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"
        default_manager_name = "objects"


class TenantModel(BaseModel):
    """
    Modelo pertencente a uma clinica (tenant).

    Toda subclasse ganha:

    * FK obrigatoria ``clinic``;
    * manager com filtro automatico pelo tenant ativo;
    * validacao no ``save()`` que impede gravar registro em outra clinica.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="clinica",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
        editable=False,
    )

    objects = TenantManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        tenant_id = get_current_tenant_id()
        if not self.clinic_id:
            if tenant_id is None and not is_unscoped():
                raise PermissionDenied(
                    "Nao e possivel gravar %s sem uma clinica ativa no contexto."
                    % self._meta.verbose_name
                )
            self.clinic_id = tenant_id
        elif tenant_id is not None and str(self.clinic_id) != str(tenant_id) and not is_unscoped():
            raise PermissionDenied(
                "Tentativa de gravar %s em clinica diferente da clinica ativa."
                % self._meta.verbose_name
            )
        return super().save(*args, **kwargs)


class ActiveStatusMixin(models.Model):
    is_active = models.BooleanField("ativo", default=True, db_index=True)

    class Meta:
        abstract = True
