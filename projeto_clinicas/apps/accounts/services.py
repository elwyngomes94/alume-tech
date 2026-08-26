"""Servicos de autenticacao: forca bruta, bloqueio, tokens e sessoes."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import ApiToken, LoginAttempt, User, UserSession
from apps.audit.models import AuditAction, AuditResult
from apps.audit.services import log_action

ATTEMPT_CACHE_PREFIX = "jja:login-attempts:"


# ---------------------------------------------------------------------------
# Protecao contra forca bruta
# ---------------------------------------------------------------------------
def _cache_key(identifier: str) -> str:
    return f"{ATTEMPT_CACHE_PREFIX}{hashlib.sha256(identifier.lower().encode()).hexdigest()}"


def attempts_for(identifier: str) -> int:
    return cache.get(_cache_key(identifier), 0)


def register_failed_attempt(identifier: str) -> int:
    key = _cache_key(identifier)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, settings.LOGIN_LOCKOUT_SECONDS)
    return attempts


def reset_attempts(identifier: str) -> None:
    cache.delete(_cache_key(identifier))


def is_throttled(identifier: str) -> bool:
    return attempts_for(identifier) >= settings.LOGIN_MAX_ATTEMPTS


def record_attempt(
    email: str, successful: bool, reason: str = "", ip: str = "", user_agent: str = ""
) -> None:
    LoginAttempt.objects.create(
        email=(email or "")[:254],
        successful=successful,
        reason=reason[:120],
        ip_address=ip[:45],
        user_agent=user_agent[:400],
    )
    log_action(
        AuditAction.LOGIN if successful else AuditAction.LOGIN_FAILED,
        description=reason or ("Autenticacao bem sucedida" if successful else "Falha de login"),
        result=AuditResult.SUCCESS if successful else AuditResult.DENIED,
        object_type="accounts.User",
        object_repr=email,
        is_sensitive=not successful,
    )


def lock_user(user: User, minutes: Optional[int] = None) -> None:
    seconds = (minutes * 60) if minutes else settings.LOGIN_LOCKOUT_SECONDS
    user.locked_until = timezone.now() + timedelta(seconds=seconds)
    user.save(update_fields=["locked_until"])
    log_action(
        AuditAction.SECURITY_ALERT,
        obj=user,
        description="Conta bloqueada temporariamente por excesso de tentativas de login",
        result=AuditResult.DENIED,
    )


def register_login_success(user: User, request) -> None:
    from apps.core.middleware import client_ip

    reset_attempts(user.email)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_ip = client_ip(request) or None
    user.save(update_fields=["failed_login_count", "locked_until", "last_login_ip"])
    track_session(user, request)


# ---------------------------------------------------------------------------
# Sessoes por dispositivo
# ---------------------------------------------------------------------------
def track_session(user: User, request) -> Optional[UserSession]:
    from apps.core.middleware import client_ip

    session_key = getattr(request.session, "session_key", None)
    if not session_key:
        return None
    session, _created = UserSession.objects.update_or_create(
        user=user,
        session_key=session_key,
        defaults={
            "ip_address": client_ip(request),
            "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:400],
            "revoked_at": None,
        },
    )
    return session


def revoke_other_sessions(user: User, keep_session_key: str) -> int:
    sessions = UserSession.objects.filter(user=user, revoked_at__isnull=True).exclude(
        session_key=keep_session_key
    )
    total = sessions.count()
    for session in sessions:
        session.revoke()
    return total


def revoke_all_sessions(user: User) -> int:
    """Encerra todas as sessoes ativas do usuario (usado ao redefinir a senha)."""
    sessions = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    total = sessions.count()
    for session in sessions:
        session.revoke()
    return total


# ---------------------------------------------------------------------------
# Definicao/redefinicao de senha por um administrador
# ---------------------------------------------------------------------------
def generate_strong_password() -> str:
    """Senha provisoria aleatoria (nao usar para outra finalidade)."""
    return secrets.token_urlsafe(10)


def admin_set_password(
    user: User, *, raw_password: Optional[str] = None, force_change: bool = True,
) -> str:
    """
    Define ou redefine a senha de um usuario a pedido de um administrador.

    Sempre encerra todas as sessoes ativas do usuario (forca novo login com a
    senha nova) e limpa bloqueios/tentativas anteriores. Retorna a senha em
    texto puro apenas para exibicao unica na tela -- nunca e persistida.
    """
    password = raw_password or generate_strong_password()
    user.set_password(password)
    user.must_change_password = force_change
    user.password_changed_at = timezone.now()
    user.locked_until = None
    user.failed_login_count = 0
    user.save(
        update_fields=[
            "password", "must_change_password", "password_changed_at",
            "locked_until", "failed_login_count",
        ]
    )
    reset_attempts(user.email)
    revoke_all_sessions(user)
    return password


# ---------------------------------------------------------------------------
# Tokens de API
# ---------------------------------------------------------------------------
def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_api_token(
    user: User, name: str, clinic=None, expires_in_days: int = 365
) -> Tuple[ApiToken, str]:
    """Cria um token de API. O valor bruto e exibido uma unica vez."""
    raw = f"jja_{secrets.token_urlsafe(32)}"
    token = ApiToken.objects.create(
        user=user,
        name=name,
        clinic=clinic,
        key_hash=hash_token(raw),
        prefix=raw[:12],
        expires_at=timezone.now() + timedelta(days=expires_in_days),
    )
    log_action(
        AuditAction.PERMISSION_CHANGE,
        obj=token,
        description=f"Token de API '{name}' criado",
    )
    return token, raw


def resolve_api_token(raw_token: str) -> Optional[ApiToken]:
    token = (
        ApiToken.objects.select_related("user", "clinic")
        .filter(key_hash=hash_token(raw_token))
        .first()
    )
    if token is None or not token.is_valid or not token.user.is_active:
        return None
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token
