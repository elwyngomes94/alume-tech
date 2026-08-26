"""
Estrutura multitenant: organizacao (grupo economico) e vinculo usuario-clinica.

    Organization (opcional)
        └── Clinic (tenant)
                └── ClinicMembership (usuario + perfil + permissoes)

O vinculo e a unica porta de entrada de um usuario em uma clinica. Sem
``ClinicMembership`` ativo (ou perfil SUPERADMIN), o usuario nao consegue
ativar o tenant e, consequentemente, nao enxerga nenhum dado da clinica.
"""
from __future__ import annotations

from typing import Set

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.accounts.permissions import Roles, default_permissions_for
from apps.core.models import ActiveStatusMixin, BaseModel


class Organization(BaseModel, ActiveStatusMixin):
    """Empresa/grupo que pode possuir varias clinicas (multiunidade)."""

    name = models.CharField("razao social", max_length=180)
    trade_name = models.CharField("nome fantasia", max_length=180, blank=True)
    slug = models.SlugField("identificador", max_length=180, unique=True)
    document = models.CharField("CNPJ", max_length=18, blank=True)
    contact_email = models.EmailField("e-mail de contato", blank=True)
    contact_phone = models.CharField("telefone", max_length=20, blank=True)

    class Meta:
        verbose_name = "organizacao"
        verbose_name_plural = "organizacoes"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.trade_name or self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.trade_name or self.name)[:180]
        return super().save(*args, **kwargs)


class ClinicMembership(BaseModel):
    """Vinculo de um usuario com uma clinica, com perfil e permissoes."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        on_delete=models.CASCADE,
        related_name="clinic_memberships",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="clinica",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        "perfil", max_length=32, choices=Roles.CHOICES, default=Roles.RECEPTIONIST
    )
    custom_role = models.ForeignKey(
        "accounts.Role",
        verbose_name="papel personalizado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships",
    )
    extra_permissions = models.JSONField("permissoes adicionais", default=list, blank=True)
    denied_permissions = models.JSONField("permissoes negadas", default=list, blank=True)
    is_active = models.BooleanField("ativo", default=True, db_index=True)
    is_default = models.BooleanField("clinica padrao do usuario", default=False)
    job_title = models.CharField("cargo", max_length=80, blank=True)
    started_at = models.DateField("inicio do vinculo", null=True, blank=True)
    ended_at = models.DateField("fim do vinculo", null=True, blank=True)

    class Meta:
        verbose_name = "vinculo com clinica"
        verbose_name_plural = "vinculos com clinicas"
        ordering = ["clinic__trade_name", "user__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "clinic"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_membership_user_clinic",
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["clinic", "role"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.clinic} ({self.get_role_display()})"

    def effective_permissions(self) -> Set[str]:
        """Permissoes = papel personalizado (ou padrao) + extras - negadas."""
        if self.role == Roles.SUPERADMIN:
            from apps.accounts.permissions import ALL_PERMISSIONS

            return set(ALL_PERMISSIONS)
        base = (
            self.custom_role.permission_set()
            if self.custom_role and self.custom_role.is_active
            else default_permissions_for(self.role)
        )
        base = set(base) | set(self.extra_permissions or [])
        return base - set(self.denied_permissions or [])
