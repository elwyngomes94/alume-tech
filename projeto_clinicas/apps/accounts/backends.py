"""Backend de autenticacao por e-mail com protecao contra forca bruta."""
from __future__ import annotations

from typing import Optional

from django.contrib.auth.backends import ModelBackend

from apps.accounts.models import User
from apps.accounts.services import (
    is_throttled,
    lock_user,
    register_failed_attempt,
    reset_attempts,
)


class ThrottledAuthentication(Exception):
    """Levantada quando o limite de tentativas foi atingido."""


class AccountLocked(Exception):
    """Levantada quando a conta esta temporariamente bloqueada."""


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs) -> Optional[User]:
        email = (username or kwargs.get("email") or "").strip().lower()
        if not email or not password:
            return None

        if is_throttled(email):
            raise ThrottledAuthentication(
                "Muitas tentativas de login. Tente novamente em alguns minutos."
            )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Executa o hash mesmo assim para evitar enumeracao por tempo de resposta.
            User().set_password(password)
            register_failed_attempt(email)
            return None

        if user.is_locked:
            raise AccountLocked("Conta temporariamente bloqueada por seguranca.")

        if user.check_password(password) and self.user_can_authenticate(user):
            reset_attempts(email)
            return user

        attempts = register_failed_attempt(email)
        User.objects.filter(pk=user.pk).update(failed_login_count=user.failed_login_count + 1)
        from django.conf import settings

        if attempts >= settings.LOGIN_MAX_ATTEMPTS:
            lock_user(user)
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except (User.DoesNotExist, ValueError, TypeError):
            return None
