"""
Automacoes financeiras (Fase 1):

* baixa automatica via webhook financeiro generico (agnostico de provedor);
* geracao automatica do comprovante de pagamento.
"""
from __future__ import annotations

import hashlib
import hmac

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.automation.services import engine


def verify_webhook_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    """Confere a assinatura HMAC-SHA256 do corpo bruto do webhook."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def process_payment_webhook(
    clinic, *, receivable_id, amount, method_id, external_reference: str = "", user=None,
) -> dict:
    """
    Registra a baixa de uma conta a receber a partir de um webhook
    financeiro. Reaproveita 100% de
    ``apps.finance.services.register_receivable_payment`` -- o mesmo
    caminho usado pela baixa manual da recepcao -- entao "nao duplicar
    lancamento" ja e garantido pela propria funcao existente (que rejeita
    valor maior que o saldo em aberto).
    """
    from apps.finance.models import PaymentMethod, ReceivableAccount
    from apps.finance.services import register_receivable_payment

    receivable = ReceivableAccount.objects.get(pk=receivable_id, clinic=clinic)
    method = PaymentMethod.objects.get(pk=method_id, clinic=clinic)
    idempotency_key = external_reference or f"{receivable_id}:{amount}:{method_id}"

    def action() -> dict:
        transaction = register_receivable_payment(
            receivable, amount=amount, method=method, user=user,
            notes=f"Baixa automatica via webhook (ref: {external_reference or 's/ referencia'})",
        )
        return {"transaction_id": str(transaction.pk)}

    execution = engine.run(
        "financial_webhook_payment", clinic,
        idempotency_key=idempotency_key, action=action, trigger_object=receivable,
    )
    if execution is None:
        return {"status": "error"}
    return {"status": execution.status, "result": execution.result}


def generate_payment_receipt(transaction) -> None:
    """
    Gera automaticamente o comprovante em PDF de um pagamento confirmado
    (baixa manual ou via webhook) e anexa como ``Document`` do paciente.
    Chamado a partir do final de
    ``apps.finance.services.register_receivable_payment``, entao cobre os
    dois caminhos com uma unica chamada.
    """
    clinic = transaction.clinic
    if not engine.get_settings(clinic).auto_generate_receipt:
        return
    if transaction.receivable_id is None:
        return  # comprovante automatico cobre apenas pagamentos de contas a receber

    def action() -> dict:
        document = _build_receipt_document(transaction)
        return {"document_id": str(document.pk)}

    engine.run(
        "payment_receipt", clinic,
        idempotency_key=str(transaction.pk), action=action, trigger_object=transaction,
    )


def _build_receipt_document(transaction):
    from apps.documents.models import Document, DocumentCategory
    from apps.reports.exporters import export_pdf

    receivable = transaction.receivable
    patient = receivable.patient
    local_paid_at = timezone.localtime(transaction.paid_at)
    headers = ["Campo", "Valor"]
    rows = [
        ["Paciente", patient.display_name if patient else receivable.description],
        [
            "Descricao",
            receivable.description or (str(receivable.service) if receivable.service_id else "-"),
        ],
        ["Data do pagamento", local_paid_at.strftime("%d/%m/%Y %H:%M")],
        ["Forma de pagamento", transaction.method.name if transaction.method_id else "-"],
        ["Valor pago", f"R$ {transaction.amount:.2f}"],
        ["Clinica", str(transaction.clinic)],
    ]
    response = export_pdf(
        f"comprovante-{transaction.pk}", headers, rows,
        title="Comprovante de pagamento", subtitle=str(transaction.clinic),
    )

    category, _created = DocumentCategory.all_objects.get_or_create(
        clinic=transaction.clinic, name="Comprovante de pagamento",
        defaults={"is_clinical": False, "visible_to_patient_default": True},
    )
    document = Document(
        clinic=transaction.clinic,
        category=category,
        title=f"Comprovante de pagamento - {local_paid_at:%d/%m/%Y}",
        patient=patient,
        uploaded_by=transaction.created_by,
        is_sensitive=False,
        visible_to_patient=True,
        file=ContentFile(response.content, name=f"comprovante-{transaction.pk}.pdf"),
    )
    document.full_clean(
        exclude=["clinic", "original_name", "content_type", "size", "checksum", "uploaded_by"]
    )
    document.save()
    return document
