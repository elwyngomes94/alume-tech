"""Regras de negocio do financeiro da clinica."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.finance.models import (
    CostCenter,
    FinancialCategory,
    FinancialStatus,
    FinancialTransaction,
    PaymentMethod,
    PayableAccount,
    ProfessionalCommissionRule,
    ReceivableAccount,
)

ZERO = Decimal("0.00")


def _as_aware_datetime(value):
    """
    Normaliza ``paid_at`` para datetime com timezone.

    O formulario de pagamento so coleta a data (nao a hora); um objeto
    ``date`` puro, se salvo direto num ``DateTimeField`` com ``USE_TZ=True``,
    vira um datetime "naive" (gera warning e perde a timezone correta).
    """
    if value is None:
        return timezone.now()
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    # objeto ``date``: usa a hora atual no dia informado.
    now = timezone.localtime()
    combined = datetime.combine(value, now.time())
    return timezone.make_aware(combined)

DEFAULT_PAYMENT_METHODS = [
    ("Dinheiro", PaymentMethod.Kind.CASH),
    ("PIX", PaymentMethod.Kind.PIX),
    ("Cartao de credito", PaymentMethod.Kind.CREDIT_CARD),
    ("Cartao de debito", PaymentMethod.Kind.DEBIT_CARD),
    ("Transferencia", PaymentMethod.Kind.TRANSFER),
    ("Boleto", PaymentMethod.Kind.BOLETO),
    ("Outros", PaymentMethod.Kind.OTHER),
]

DEFAULT_INCOME_CATEGORIES = ["Consultas", "Procedimentos", "Convenios", "Outras receitas"]

DEFAULT_EXPENSE_CATEGORIES = [
    "Salarios", "Profissionais", "Aluguel", "Energia", "Agua", "Internet",
    "Materiais", "Medicamentos", "Equipamentos", "Manutencao", "Impostos",
    "Marketing", "Sistemas", "Outros",
]


def create_receipt_document(clinic, user, upload):
    """
    Cria o Document de comprovante financeiro anexado a uma conta a pagar.

    Reaproveita o storage privado e a categoria de documentos ja existentes
    em vez de duplicar logica de upload.
    """
    from apps.documents.models import Document, DocumentCategory

    category, _created = DocumentCategory.all_objects.get_or_create(
        clinic=clinic, name="Comprovante financeiro",
        defaults={"is_clinical": False, "visible_to_patient_default": False},
    )
    document = Document(
        clinic=clinic, category=category, title=f"Comprovante - {upload.name}",
        file=upload, uploaded_by=user, is_sensitive=False,
    )
    document.full_clean(exclude=["clinic", "original_name", "content_type", "size", "checksum"])
    document.save()
    return document


def provision_finance_defaults(clinic) -> None:
    """
    Cria formas de pagamento e categorias padrao para a clinica.

    Idempotente (``get_or_create``) -- pode ser chamada tanto no
    provisionamento de uma clinica nova quanto num backfill de clinicas
    existentes.
    """
    for name, kind in DEFAULT_PAYMENT_METHODS:
        PaymentMethod.all_objects.get_or_create(
            clinic=clinic, name=name, defaults={"kind": kind}
        )
    for name in DEFAULT_INCOME_CATEGORIES:
        FinancialCategory.all_objects.get_or_create(
            clinic=clinic, kind=FinancialCategory.Kind.INCOME, name=name,
        )
    for name in DEFAULT_EXPENSE_CATEGORIES:
        FinancialCategory.all_objects.get_or_create(
            clinic=clinic, kind=FinancialCategory.Kind.EXPENSE, name=name,
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def _recompute_status(account) -> None:
    """Recalcula pending/partial/paid/overdue a partir do saldo pago."""
    if account.status in (FinancialStatus.CANCELED, FinancialStatus.REFUNDED, FinancialStatus.COURTESY):
        return
    paid = account.paid_amount
    total = account.net_amount if isinstance(account, ReceivableAccount) else account.amount
    if paid <= ZERO:
        status = FinancialStatus.PENDING
    elif paid < total:
        status = FinancialStatus.PARTIAL
    else:
        status = FinancialStatus.PAID
    if status == FinancialStatus.PENDING and account.due_date < timezone.localdate():
        status = FinancialStatus.OVERDUE
    if status != account.status:
        account.status = status
        account.save(update_fields=["status", "updated_at"])


def refresh_overdue_statuses(clinic) -> int:
    """Marca como vencidas as contas pendentes cujo vencimento passou."""
    today = timezone.localdate()
    updated = 0
    for model in (ReceivableAccount, PayableAccount):
        updated += model.objects.filter(
            status=FinancialStatus.PENDING, due_date__lt=today
        ).update(status=FinancialStatus.OVERDUE)
    return updated


# ---------------------------------------------------------------------------
# Comissao
# ---------------------------------------------------------------------------
def resolve_commission_rule(professional, service) -> Optional[ProfessionalCommissionRule]:
    if professional is None:
        return None
    queryset = ProfessionalCommissionRule.objects.filter(is_active=True, professional=professional)
    if service is not None:
        specific = queryset.filter(service=service).first()
        if specific is not None:
            return specific
    return queryset.filter(service__isnull=True).first()


def apply_commission(receivable: ReceivableAccount) -> None:
    """Calcula e grava a comissao do profissional quando a conta e quitada."""
    if receivable.professional_id is None:
        return
    rule = resolve_commission_rule(receivable.professional, receivable.service)
    commission = rule.compute(receivable.net_amount) if rule else ZERO
    receivable.professional_commission_amount = commission
    receivable.clinic_amount = receivable.net_amount - commission
    receivable.save(update_fields=["professional_commission_amount", "clinic_amount", "updated_at"])


# ---------------------------------------------------------------------------
# Pagamentos / lancamentos
# ---------------------------------------------------------------------------
@transaction.atomic
def register_receivable_payment(
    receivable: ReceivableAccount, *, amount: Decimal, method: PaymentMethod, user=None,
    paid_at=None, notes: str = "",
) -> FinancialTransaction:
    if amount <= ZERO:
        raise ValidationError("O valor do pagamento deve ser maior que zero.")
    if amount > receivable.balance:
        raise ValidationError(
            f"O valor informado (R$ {amount}) e maior que o saldo em aberto "
            f"(R$ {receivable.balance})."
        )
    entry = FinancialTransaction.objects.create(
        clinic=receivable.clinic,
        kind=FinancialTransaction.Kind.INCOME,
        receivable=receivable,
        category=receivable.category,
        amount=amount,
        method=method,
        paid_at=_as_aware_datetime(paid_at),
        created_by=user,
        notes=notes,
    )
    _recompute_status(receivable)
    if receivable.status == FinancialStatus.PAID:
        apply_commission(receivable)
    _generate_receipt_if_enabled(entry)
    return entry


def _generate_receipt_if_enabled(transaction_entry: FinancialTransaction) -> None:
    """
    Gera automaticamente o comprovante de pagamento (Fase 1 do motor de
    automacao), se o modulo estiver habilitado na clinica. Nunca interrompe
    o registro do pagamento se a automacao nao estiver disponivel ou algo
    falhar -- mesmo padrao defensivo usado em todo o sistema para
    integracoes acessorias.
    """
    try:
        if not transaction_entry.clinic.has_module("automation"):
            return
        from apps.automation.services.financial_automation import generate_payment_receipt

        generate_payment_receipt(transaction_entry)
    except Exception:  # pragma: no cover - nunca bloqueia o registro do pagamento
        import logging

        logging.getLogger("jja.security").exception(
            "Falha ao gerar comprovante automatico da transacao %s", transaction_entry.pk
        )


@transaction.atomic
def register_payable_payment(
    payable: PayableAccount, *, amount: Decimal, method: PaymentMethod, user=None,
    paid_at=None, notes: str = "",
) -> FinancialTransaction:
    if amount <= ZERO:
        raise ValidationError("O valor do pagamento deve ser maior que zero.")
    if amount > payable.balance:
        raise ValidationError(
            f"O valor informado (R$ {amount}) e maior que o saldo em aberto "
            f"(R$ {payable.balance})."
        )
    entry = FinancialTransaction.objects.create(
        clinic=payable.clinic,
        kind=FinancialTransaction.Kind.EXPENSE,
        payable=payable,
        category=payable.category,
        cost_center=payable.cost_center,
        amount=amount,
        method=method,
        paid_at=_as_aware_datetime(paid_at),
        created_by=user,
        notes=notes,
    )
    _recompute_status(payable)
    return entry


@transaction.atomic
def cancel_receivable(receivable: ReceivableAccount, *, reason: str = "") -> None:
    receivable.status = FinancialStatus.CANCELED
    if reason:
        receivable.notes = f"{receivable.notes}\nCancelado: {reason}".strip()
    receivable.save(update_fields=["status", "notes", "updated_at"])


@transaction.atomic
def refund_receivable_payment(
    receivable: ReceivableAccount, *, amount: Decimal, method: PaymentMethod, user=None,
    reason: str = "",
) -> FinancialTransaction:
    """
    Registra o estorno de valores ja recebidos numa conta (cancelamento de
    agendamento ja pago). Gera um lancamento negativo no fluxo de caixa e
    marca a conta como estornada -- nunca apaga o pagamento original, que
    permanece no historico para auditoria.
    """
    if amount <= ZERO:
        raise ValidationError("O valor do estorno deve ser maior que zero.")
    if amount > receivable.paid_amount:
        raise ValidationError(
            f"O valor do estorno (R$ {amount}) e maior que o valor recebido "
            f"(R$ {receivable.paid_amount})."
        )
    entry = FinancialTransaction.objects.create(
        clinic=receivable.clinic,
        kind=FinancialTransaction.Kind.REFUND,
        receivable=receivable,
        category=receivable.category,
        amount=amount,
        method=method,
        created_by=user,
        notes=reason,
    )
    receivable.status = FinancialStatus.REFUNDED
    if reason:
        receivable.notes = f"{receivable.notes}\nEstornado: {reason}".strip()
    receivable.save(update_fields=["status", "notes", "updated_at"])
    return entry


@transaction.atomic
def cancel_payable(payable: PayableAccount, *, reason: str = "") -> None:
    payable.status = FinancialStatus.CANCELED
    if reason:
        payable.notes = f"{payable.notes}\nCancelado: {reason}".strip()
    payable.save(update_fields=["status", "notes", "updated_at"])


def create_manual_transaction(
    *, clinic, kind: str, amount: Decimal, method: PaymentMethod, category=None,
    cost_center=None, user=None, paid_at=None, notes: str = "",
) -> FinancialTransaction:
    """Lancamento avulso (nao ligado a uma conta a pagar/receber)."""
    if amount <= ZERO:
        raise ValidationError("O valor deve ser maior que zero.")
    return FinancialTransaction.objects.create(
        clinic=clinic, kind=kind, amount=amount, method=method, category=category,
        cost_center=cost_center, created_by=user, paid_at=_as_aware_datetime(paid_at),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Fluxo de caixa
# ---------------------------------------------------------------------------
@dataclass
class CashFlowEntry:
    transaction: FinancialTransaction
    running_balance: Decimal


def _bounds(start: date, end: date):
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(end, time.max), tz),
    )


def opening_balance(clinic, before: date) -> Decimal:
    start_dt, _ = _bounds(before, before)
    totals = FinancialTransaction.objects.filter(paid_at__lt=start_dt).aggregate(
        income=Sum("amount", filter=_income_filter()),
        expense=Sum("amount", filter=_expense_filter()),
    )
    return (totals["income"] or ZERO) - (totals["expense"] or ZERO)


def _income_filter():
    from django.db.models import Q

    return Q(kind=FinancialTransaction.Kind.INCOME)


def _expense_filter():
    from django.db.models import Q

    return Q(kind=FinancialTransaction.Kind.EXPENSE)


def cashflow_entries(clinic, start: date, end: date, **filters) -> List[CashFlowEntry]:
    """Lista cronologica de lancamentos com saldo corrente acumulado."""
    start_dt, end_dt = _bounds(start, end)
    queryset = (
        FinancialTransaction.objects.filter(paid_at__gte=start_dt, paid_at__lte=end_dt)
        .select_related("method", "category", "cost_center", "receivable__patient",
                         "payable")
        .order_by("paid_at")
    )
    if filters.get("category"):
        queryset = queryset.filter(category_id=filters["category"])
    if filters.get("method"):
        queryset = queryset.filter(method_id=filters["method"])
    if filters.get("cost_center"):
        queryset = queryset.filter(cost_center_id=filters["cost_center"])
    if filters.get("professional"):
        queryset = queryset.filter(receivable__professional_id=filters["professional"])
    if filters.get("kind"):
        queryset = queryset.filter(kind=filters["kind"])

    balance = opening_balance(clinic, start)
    entries: List[CashFlowEntry] = []
    for entry in queryset:
        signed = entry.amount if entry.kind == FinancialTransaction.Kind.INCOME else -entry.amount
        balance += signed
        entries.append(CashFlowEntry(transaction=entry, running_balance=balance))
    return entries


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard_summary(clinic, start: date, end: date) -> dict:
    start_dt, end_dt = _bounds(start, end)
    period_transactions = FinancialTransaction.objects.filter(
        paid_at__gte=start_dt, paid_at__lte=end_dt
    )
    income = period_transactions.filter(kind=FinancialTransaction.Kind.INCOME).aggregate(
        total=Sum("amount")
    )["total"] or ZERO
    expense = period_transactions.filter(kind=FinancialTransaction.Kind.EXPENSE).aggregate(
        total=Sum("amount")
    )["total"] or ZERO

    active_receivables = ReceivableAccount.objects.exclude(
        status__in=[FinancialStatus.PAID, FinancialStatus.CANCELED]
    )
    active_payables = PayableAccount.objects.exclude(
        status__in=[FinancialStatus.PAID, FinancialStatus.CANCELED]
    )
    today = timezone.localdate()

    receivables_open = sum((r.balance for r in active_receivables), ZERO)
    payables_open = sum((p.balance for p in active_payables), ZERO)
    receivables_overdue = sum(
        (r.balance for r in active_receivables if r.due_date < today), ZERO
    )
    payables_overdue = sum(
        (p.balance for p in active_payables if p.due_date < today), ZERO
    )

    current_balance = opening_balance(clinic, today + timedelta(days=1))

    by_day = {}
    for entry in period_transactions.order_by("paid_at"):
        key = timezone.localtime(entry.paid_at).strftime("%d/%m")
        bucket = by_day.setdefault(key, {"income": ZERO, "expense": ZERO})
        if entry.kind == FinancialTransaction.Kind.INCOME:
            bucket["income"] += entry.amount
        else:
            bucket["expense"] += entry.amount

    return {
        "current_balance": current_balance,
        "period_income": income,
        "period_expense": expense,
        "period_result": income - expense,
        "receivables_open": receivables_open,
        "payables_open": payables_open,
        "receivables_overdue": receivables_overdue,
        "payables_overdue": payables_overdue,
        "chart_labels": list(by_day.keys()),
        "chart_income": [float(v["income"]) for v in by_day.values()],
        "chart_expense": [float(v["expense"]) for v in by_day.values()],
    }
