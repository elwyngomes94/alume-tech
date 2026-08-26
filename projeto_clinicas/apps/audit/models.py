"""
Trilha de auditoria do JJA System.

O registro e **append-only**: uma vez gravado, o log nao pode ser alterado nem
excluido pela aplicacao (tentativas levantam excecao). Isso atende ao requisito
de logs que nao possam ser adulterados por usuarios comuns.
"""
from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    LOGIN = "login", "Login"
    LOGIN_FAILED = "login_failed", "Falha de login"
    LOGOUT = "logout", "Logout"
    PASSWORD_CHANGE = "password_change", "Alteracao de senha"
    MFA_CHANGE = "mfa_change", "Alteracao de MFA"
    CREATE = "create", "Criacao"
    UPDATE = "update", "Alteracao"
    DELETE = "delete", "Exclusao"
    VIEW = "view", "Visualizacao"
    VIEW_SENSITIVE = "view_sensitive", "Visualizacao de dado sensivel"
    DOWNLOAD = "download", "Download de documento"
    UPLOAD = "upload", "Upload de documento"
    EXPORT = "export", "Exportacao de dados"
    PERMISSION_CHANGE = "permission_change", "Alteracao de permissoes"
    SETTINGS_CHANGE = "settings_change", "Alteracao de configuracoes"
    ACCESS_DENIED = "access_denied", "Acesso negado"
    TENANT_SWITCH = "tenant_switch", "Troca de clinica"
    PLATFORM_ACCESS = "platform_access", "Acesso administrativo global"
    SECURITY_ALERT = "security_alert", "Alerta de seguranca"


class AuditResult(models.TextChoices):
    SUCCESS = "success", "Sucesso"
    DENIED = "denied", "Negado"
    ERROR = "error", "Erro"


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("data/hora", auto_now_add=True, db_index=True)

    # Quem
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    user_email = models.CharField("e-mail (snapshot)", max_length=254, blank=True)
    user_role = models.CharField("perfil", max_length=32, blank=True)

    # Onde
    clinic = models.ForeignKey(
        "clinics.Clinic",
        verbose_name="clinica",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    clinic_name = models.CharField("clinica (snapshot)", max_length=180, blank=True)

    # O que
    action = models.CharField("acao", max_length=32, choices=AuditAction.choices, db_index=True)
    object_type = models.CharField("tipo do objeto", max_length=120, blank=True, db_index=True)
    object_id = models.CharField("id do objeto", max_length=64, blank=True, db_index=True)
    object_repr = models.CharField("objeto", max_length=250, blank=True)
    description = models.TextField("descricao", blank=True)
    changes = models.JSONField("alteracoes", default=dict, blank=True)
    result = models.CharField(
        "resultado", max_length=16, choices=AuditResult.choices, default=AuditResult.SUCCESS
    )
    is_sensitive = models.BooleanField("dado sensivel", default=False, db_index=True)

    # Como
    ip_address = models.CharField("IP", max_length=45, blank=True)
    user_agent = models.CharField("user-agent", max_length=400, blank=True)
    path = models.CharField("rota", max_length=255, blank=True)
    method = models.CharField("metodo", max_length=10, blank=True)
    session_key = models.CharField("sessao", max_length=64, blank=True)

    #: Encadeamento de integridade (detecta remocao/alteracao de registros).
    checksum = models.CharField(max_length=64, blank=True, editable=False)
    previous_checksum = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"[{self.created_at:%d/%m/%Y %H:%M}] {self.user_email} {self.action}"

    # -- imutabilidade ------------------------------------------------------
    def save(self, *args, **kwargs):
        if self._state.adding is False:
            raise PermissionError("Registros de auditoria sao imutaveis.")
        self.checksum = self.compute_checksum()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # pragma: no cover - protecao explicita
        raise PermissionError("Registros de auditoria nao podem ser excluidos.")

    def compute_checksum(self) -> str:
        payload = "|".join(
            str(value)
            for value in (
                self.id,
                self.user_email,
                self.clinic_id,
                self.action,
                self.object_type,
                self.object_id,
                self.result,
                self.ip_address,
                self.previous_checksum,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def action_label(self) -> str:
        return self.get_action_display()
