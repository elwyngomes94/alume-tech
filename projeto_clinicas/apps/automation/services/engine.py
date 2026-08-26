"""
Motor central de automacao: trigger -> condition -> action -> execution -> log.

``run()`` nunca lanca excecao para quem chamou -- mesmo padrao defensivo ja
usado em ``apps.scheduling.services._notify``/``_create_receivable_draft``:
uma falha numa automacao nunca pode travar o fluxo principal (agenda,
financeiro) que a disparou. Tambem garante idempotencia (a mesma automacao,
clinica e chave nunca repete a acao de sucesso) e entra explicitamente no
contexto de tenant da clinica informada, para funcionar tanto disparado de
dentro de uma requisicao quanto de um webhook sem sessao.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from django.contrib.contenttypes.models import ContentType

from apps.automation.models import Automation, AutomationExecution, AutomationSettings
from apps.core.tenancy import tenant_context

logger = logging.getLogger("jja.security")


def get_settings(clinic) -> AutomationSettings:
    """Configuracao de automacao da clinica (cria com os padroes se nao existir)."""
    settings_obj, _created = AutomationSettings.objects.get_or_create(clinic=clinic)
    return settings_obj


def run(
    codename: str,
    clinic,
    *,
    idempotency_key: str,
    action: Callable[[], Optional[dict]],
    condition: Optional[Callable[[], bool]] = None,
    trigger_object=None,
) -> Optional[AutomationExecution]:
    """
    Executa uma automacao com idempotencia, log e blindagem de erro.

    Retorna a ``AutomationExecution`` (a existente, se ja havia sido
    executada com sucesso antes com a mesma chave; uma nova, caso
    contrario) ou ``None`` se o codigo da automacao for desconhecido.
    """
    try:
        automation = Automation.objects.get(codename=codename)
    except Automation.DoesNotExist:
        logger.error("Automacao desconhecida: %s", codename)
        return None

    with tenant_context(clinic):
        existing = AutomationExecution.objects.filter(
            clinic=clinic, automation=automation, idempotency_key=idempotency_key,
            status=AutomationExecution.Status.SUCCESS,
        ).first()
        if existing is not None:
            return existing

        content_type = None
        object_id = ""
        if trigger_object is not None:
            content_type = ContentType.objects.get_for_model(trigger_object)
            object_id = str(trigger_object.pk)

        execution = AutomationExecution.objects.create(
            clinic=clinic, automation=automation, idempotency_key=idempotency_key,
            trigger_content_type=content_type, trigger_object_id=object_id,
        )
        try:
            if condition is not None and not condition():
                execution.mark_skipped()
                return execution
            result = action()
            execution.mark_success(result if isinstance(result, dict) else None)
        except Exception as exc:  # pragma: no cover - nunca deve travar o fluxo principal
            logger.exception(
                "Falha na automacao %s (clinica=%s)", codename, getattr(clinic, "pk", None)
            )
            execution.mark_failed(str(exc))
        return execution
