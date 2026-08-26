"""Tratamento padronizado de erros da API."""
from __future__ import annotations

import logging
import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("jja.security")


def jja_exception_handler(exc, context):
    """
    Converte excecoes em respostas JSON consistentes.

    Erros internos nao vazam detalhes: o cliente recebe apenas um
    identificador para correlacionar com o log do servidor.
    """
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=getattr(exc, "messages", [str(exc)]))
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied(detail=str(exc) or "Acesso negado.")
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound(detail="Registro nao encontrado.")

    response = exception_handler(exc, context)
    if response is not None:
        response.data = {
            "erro": True,
            "status": response.status_code,
            "detalhe": response.data,
        }
        return response

    incident = uuid.uuid4().hex[:12]
    logger.exception("erro-api incidente=%s", incident)
    return Response(
        {
            "erro": True,
            "status": 500,
            "detalhe": "Erro interno. Informe o identificador ao suporte.",
            "incidente": incident,
        },
        status=500,
    )
