"""Modelo de usuario customizado, papeis personalizados e controle de sessoes."""
from __future__ import annotations

import uuid
from typing import Optional, Set

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.accounts.permissions import ALL_PERMISSIONS, Roles, default_permissions_for
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_cpf, validate_phone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: Optional[str], **extra):
        if not email:
            raise ValueError("O e-mail e obrigatorio.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.password_changed_at = timezone.now()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: Optional[str] = None, **extra):
        extra.setdefault("role", Roles.PATIENT)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: Optional[str] = None, **extra):
        extra.setdefault("role", Roles.SUPERADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra.get("is_superuser") is not True:
            raise ValueError("Superusuario precisa de is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """
    Usuario da plataforma.

    O usuario e global (um e-mail = uma conta), mas o acesso aos dados sempre
    passa pelos vinculos com clinicas (``tenants.ClinicMembership``).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("e-mail", unique=True, db_index=True)
    full_name = models.CharField("nome completo", max_length=180)
    cpf = models.CharField(
        "CPF", max_length=14, blank=True, validators=[validate_cpf], db_index=True
    )
    phone = models.CharField("telefone", max_length=20, blank=True, validators=[validate_phone])
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    avatar = models.ImageField("foto", upload_to="avatars/", blank=True, null=True)

    role = models.CharField(
        "perfil principal", max_length=32, choices=Roles.CHOICES, default=Roles.PATIENT
    )

    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acessa o admin do Django", default=False)

    # Seguranca
    mfa_enabled = models.BooleanField("MFA ativo", default=False)
    mfa_secret = models.CharField(max_length=64, blank=True, editable=False)
    mfa_confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    must_change_password = models.BooleanField("deve trocar a senha", default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True, editable=False)
    failed_login_count = models.PositiveIntegerField(default=0, editable=False)
    locked_until = models.DateTimeField("bloqueado ate", null=True, blank=True, editable=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, editable=False)

    # LGPD
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["full_name"]
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    # -- identidade ---------------------------------------------------------
    def get_full_name(self) -> str:
        return self.full_name

    def get_short_name(self) -> str:
        return self.full_name.split(" ")[0] if self.full_name else self.email

    @property
    def initials(self) -> str:
        parts = [p for p in self.full_name.split(" ") if p]
        if not parts:
            return self.email[:2].upper()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @property
    def is_saved(self) -> bool:
        """Ja persistido no banco (ver UUIDModel.is_saved para o motivo)."""
        return not self._state.adding

    # -- perfis -------------------------------------------------------------
    @property
    def is_superadmin(self) -> bool:
        return self.role == Roles.SUPERADMIN or self.is_superuser

    @property
    def is_patient(self) -> bool:
        return self.role == Roles.PATIENT

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    # -- vinculos com clinicas ---------------------------------------------
    def memberships_queryset(self):
        from apps.tenants.models import ClinicMembership

        return (
            ClinicMembership.all_objects.filter(user=self, is_active=True, is_deleted=False)
            .select_related("clinic", "custom_role")
            .filter(clinic__is_deleted=False)
        )

    def accessible_clinics(self):
        from apps.clinics.models import Clinic

        if self.is_superadmin:
            return Clinic.objects.all()
        ids = self.memberships_queryset().values_list("clinic_id", flat=True)
        return Clinic.objects.filter(id__in=list(ids))

    def membership_for(self, clinic) -> Optional["object"]:
        if clinic is None:
            return None
        clinic_id = getattr(clinic, "pk", clinic)
        return self.memberships_queryset().filter(clinic_id=clinic_id).first()

    def role_in(self, clinic) -> Optional[str]:
        if self.is_superadmin:
            return Roles.SUPERADMIN
        membership = self.membership_for(clinic)
        return membership.role if membership else None

    def clinic_permissions(self, clinic) -> Set[str]:
        """Conjunto de permissoes efetivas do usuario na clinica informada."""
        if self.is_superadmin:
            return set(ALL_PERMISSIONS)
        membership = self.membership_for(clinic)
        if membership is None:
            return set()
        return membership.effective_permissions()

    def has_clinic_perm(self, codename: str, clinic=None) -> bool:
        """
        Verifica uma permissao dentro de uma clinica.

        Sem clinica informada, usa o tenant ativo do contexto. Sem tenant
        ativo, retorna ``False`` (falha fechada).
        """
        from apps.core.tenancy import get_current_tenant

        if not self.is_authenticated or not self.is_active:
            return False
        clinic = clinic or get_current_tenant()
        if clinic is None:
            return False
        return codename in self.clinic_permissions(clinic)

    def can_access_clinic(self, clinic) -> bool:
        if not self.is_active or clinic is None:
            return False
        if self.is_superadmin:
            return True
        return self.membership_for(clinic) is not None


class Role(TimeStampedModel):
    """
    Papel personalizado de uma clinica.

    Permite que cada clinica ajuste as permissoes de um perfil base sem
    alteracao de codigo (requisito de permissoes configuraveis).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="clinica",
        on_delete=models.CASCADE,
        related_name="roles",
        null=True,
        blank=True,
        help_text="Vazio = modelo global disponivel para todas as clinicas.",
    )
    name = models.CharField("nome", max_length=80)
    base_role = models.CharField(
        "perfil base", max_length=32, choices=Roles.CHOICES, default=Roles.RECEPTIONIST
    )
    permissions = models.JSONField("permissoes", default=list, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    description = models.TextField("descricao", blank=True)

    class Meta:
        verbose_name = "papel"
        verbose_name_plural = "papeis"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["clinic", "name"], name="uniq_role_name_per_clinic")
        ]

    def __str__(self) -> str:
        return self.name

    def permission_set(self) -> Set[str]:
        declared = {p for p in (self.permissions or []) if p in ALL_PERMISSIONS}
        return declared or default_permissions_for(self.base_role)

    @property
    def is_saved(self) -> bool:
        """Ja persistido no banco (ver UUIDModel.is_saved para o motivo)."""
        return not self._state.adding


class LoginAttempt(models.Model):
    """Registro de tentativas de autenticacao (deteccao de forca bruta)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.CharField(max_length=254, db_index=True)
    successful = models.BooleanField(default=False, db_index=True)
    ip_address = models.CharField(max_length=45, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "tentativa de login"
        verbose_name_plural = "tentativas de login"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "-created_at"])]

    def __str__(self) -> str:
        status = "sucesso" if self.successful else "falha"
        return f"{self.email} ({status})"


class UserSession(models.Model):
    """Sessoes ativas por dispositivo, permitindo revogacao pelo usuario."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    session_key = models.CharField(max_length=64, db_index=True)
    ip_address = models.CharField(max_length=45, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "sessao"
        verbose_name_plural = "sessoes"
        ordering = ["-last_activity"]

    def __str__(self) -> str:
        return f"{self.user.email} - {self.ip_address}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def revoke(self) -> None:
        from django.contrib.sessions.models import Session

        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])
        Session.objects.filter(session_key=self.session_key).delete()


class ApiToken(TimeStampedModel):
    """Token de API por usuario (integracoes e futuro aplicativo mobile)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField("descricao", max_length=80)
    key_hash = models.CharField(max_length=128, unique=True, editable=False)
    prefix = models.CharField(max_length=12, editable=False)
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="api_tokens",
        null=True,
        blank=True,
        help_text="Restringe o token a uma clinica especifica.",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "token de API"
        verbose_name_plural = "tokens de API"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}...)"

    @property
    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True
