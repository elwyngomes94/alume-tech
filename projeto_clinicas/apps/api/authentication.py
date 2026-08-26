"""Autenticacao por token para a API v1."""
from __future__ import annotations

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from apps.accounts.services import resolve_api_token
from apps.core.tenancy import set_current_tenant


class ApiTokenAuthentication(BaseAuthentication):
    """
    Autenticacao via cabecalho ``Authorization: Bearer <token>``.

    O token pode estar vinculado a uma clinica especifica; nesse caso o tenant
    ja e ativado aqui, garantindo o isolamento tambem em chamadas de API.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(f"{self.keyword} "):
            return None
        raw_token = header[len(self.keyword) + 1 :].strip()
        if not raw_token:
            raise exceptions.AuthenticationFailed("Token vazio.")

        token = resolve_api_token(raw_token)
        if token is None:
            raise exceptions.AuthenticationFailed("Token invalido ou expirado.")

        user = token.user
        if not user.is_active:
            raise exceptions.AuthenticationFailed("Usuario inativo.")

        if token.clinic_id is not None:
            clinic = token.clinic
            if not user.can_access_clinic(clinic):
                raise exceptions.AuthenticationFailed("Token sem vinculo valido com a clinica.")
            set_current_tenant(clinic)
            request.clinic = clinic
            request.clinic_permissions = frozenset(user.clinic_permissions(clinic))
        return (user, token)

    def authenticate_header(self, request):
        return self.keyword
