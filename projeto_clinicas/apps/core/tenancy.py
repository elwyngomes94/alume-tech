"""
Contexto de tenant (clinica) do JJA System.

Este modulo e a base do isolamento multitenant. O tenant ativo fica armazenado
em um contexto local da thread/task assincrona (``contextvars``), sendo
definido pelo middleware a partir da sessao do usuario autenticado -- nunca
apenas a partir da URL.

Regra fundamental:

* Modelos que pertencem a uma clinica usam ``TenantManager``.
* Sem tenant ativo, ``Model.objects`` retorna ``none()``.
* Para operacoes administrativas globais e necessario entrar explicitamente em
  :func:`unscoped`, que exige justificativa e e registrada em auditoria.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Iterator, Optional

if TYPE_CHECKING:  # pragma: no cover
    from apps.clinics.models import Clinic

logger = logging.getLogger("jja.security")

_current_tenant: ContextVar[Optional["Clinic"]] = ContextVar("jja_current_tenant", default=None)
_current_user: ContextVar[Optional[Any]] = ContextVar("jja_current_user", default=None)
_request_meta: ContextVar[dict] = ContextVar("jja_request_meta", default={})
_unscoped: ContextVar[Optional[str]] = ContextVar("jja_unscoped_reason", default=None)


# ---------------------------------------------------------------------------
# Tenant ativo
# ---------------------------------------------------------------------------
def get_current_tenant() -> Optional["Clinic"]:
    """Retorna a clinica ativa no contexto atual (ou ``None``)."""
    return _current_tenant.get()


def get_current_tenant_id():
    tenant = _current_tenant.get()
    return tenant.pk if tenant is not None else None


def set_current_tenant(clinic: Optional["Clinic"]):
    """Define a clinica ativa. Retorna o token para restauracao posterior."""
    return _current_tenant.set(clinic)


def clear_current_tenant() -> None:
    _current_tenant.set(None)


@contextmanager
def tenant_context(clinic: Optional["Clinic"]) -> Iterator[Optional["Clinic"]]:
    """Executa um bloco de codigo com a clinica informada como tenant ativo."""
    token = _current_tenant.set(clinic)
    try:
        yield clinic
    finally:
        _current_tenant.reset(token)


# ---------------------------------------------------------------------------
# Acesso global (SUPERADMIN / rotinas de sistema)
# ---------------------------------------------------------------------------
def is_unscoped() -> bool:
    return _unscoped.get() is not None


def current_unscoped_reason() -> Optional[str]:
    return _unscoped.get()


@contextmanager
def unscoped(reason: str) -> Iterator[None]:
    """
    Desativa temporariamente o filtro automatico por tenant.

    Uso restrito a: painel do SUPERADMIN, rotinas de manutencao, migracoes,
    tarefas assincronas de plataforma e testes. A justificativa e obrigatoria e
    fica registrada no log de seguranca.
    """
    if not reason:
        raise ValueError("E obrigatorio informar a justificativa do acesso global.")
    token = _unscoped.set(reason)
    user = get_current_user()
    logger.info(
        "acesso-global-iniciado reason=%s user=%s",
        reason,
        getattr(user, "email", "sistema"),
    )
    try:
        yield
    finally:
        _unscoped.reset(token)


# ---------------------------------------------------------------------------
# Usuario e metadados da requisicao (usados pela auditoria)
# ---------------------------------------------------------------------------
def get_current_user():
    return _current_user.get()


def set_current_user(user):
    return _current_user.set(user)


def get_request_meta() -> dict:
    return _request_meta.get() or {}


def set_request_meta(meta: dict):
    return _request_meta.set(meta or {})


@contextmanager
def request_context(user=None, meta: Optional[dict] = None) -> Iterator[None]:
    user_token = _current_user.set(user)
    meta_token = _request_meta.set(meta or {})
    try:
        yield
    finally:
        _current_user.reset(user_token)
        _request_meta.reset(meta_token)


class TenantContextError(RuntimeError):
    """Erro levantado quando uma operacao exige tenant e nao existe contexto."""


def require_tenant() -> "Clinic":
    tenant = get_current_tenant()
    if tenant is None:
        raise TenantContextError("Operacao exige uma clinica ativa no contexto.")
    return tenant
