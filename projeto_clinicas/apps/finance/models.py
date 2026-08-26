"""
Financeiro da clinica.

Contas a receber, contas a pagar, fluxo de caixa (ledger unico de
transacoes), categorias/centros de custo/formas de pagamento configuraveis e
comissao de profissionais. Tudo herda de ``TenantModel``: isolamento por
clinica e automatico e falha fechada, exatamente como pacientes/agendamentos.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ActiveStatusMixin, TenantModel

ZERO = Decimal("0.00")


class PaymentMethod(TenantModel, ActiveStatusMixin):
    """Forma de pagamento configuravel pela clinica."""

    class Kind(models.TextChoices):
        CASH = "cash", "Dinheiro"
        PIX = "pix", "PIX"
        CREDIT_CARD = "credit_card", "Cartao de credito"
        DEBIT_CARD = "debit_card", "Cartao de debito"
        TRANSFER = "transfer", "Transferencia"
        BOLETO = "boleto", "Boleto"
        OTHER = "other", "Outros"

    name = models.CharField("nome", max_length=80)
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.OTHER)

    class Meta:
        verbose_name = "forma de pagamento"
        verbose_name_plural = "formas de pagamento"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_payment_method_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class FinancialCategory(TenantModel, ActiveStatusMixin):
    """Categoria de receita ou despesa, configuravel pela clinica."""

    class Kind(models.TextChoices):
        INCOME = "income", "Receita"
        EXPENSE = "expense", "Despesa"

    name = models.CharField("nome", max_length=100)
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, db_index=True)
    description = models.CharField("descricao", max_length=250, blank=True)

    class Meta:
        verbose_name = "categoria financeira"
        verbose_name_plural = "categorias financeiras"
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "kind", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_financial_category_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class CostCenter(TenantModel, ActiveStatusMixin):
    """Centro de custo configuravel pela clinica."""

    name = models.CharField("nome", max_length=100)
    description = models.CharField("descricao", max_length=250, blank=True)

    class Meta:
        verbose_name = "centro de custo"
        verbose_name_plural = "centros de custo"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_cost_center_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class FinancialStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    PARTIAL = "partial", "Parcialmente pago"
    PAID = "paid", "Pago"
    OVERDUE = "overdue", "Vencido"
    CANCELED = "canceled", "Cancelado"
    COURTESY = "courtesy", "Cortesia"
    REFUNDED = "refunded", "Estornado"


class ReceivableAccount(TenantModel):
    """Conta a receber (receita da clinica)."""

    patient = models.ForeignKey(
        "patients.Patient", verbose_name="paciente", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="receivables",
    )
    professional = models.ForeignKey(
        "professionals.Professional", verbose_name="profissional responsavel",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="receivables",
    )
    service = models.ForeignKey(
        "clinics.Service", verbose_name="procedimento/servico", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="receivables",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment", verbose_name="agendamento", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="receivables",
    )
    category = models.ForeignKey(
        FinancialCategory, verbose_name="categoria", on_delete=models.PROTECT,
        related_name="receivables", limit_choices_to={"kind": FinancialCategory.Kind.INCOME},
    )
    description = models.CharField("descricao", max_length=200, blank=True)
    service_date = models.DateField("data do atendimento", default=timezone.localdate)
    due_date = models.DateField("data de vencimento")
    gross_amount = models.DecimalField("valor bruto", max_digits=10, decimal_places=2)
    discount = models.DecimalField("desconto", max_digits=10, decimal_places=2, default=ZERO)
    addition = models.DecimalField("acrescimo", max_digits=10, decimal_places=2, default=ZERO)
    expected_payment_method = models.ForeignKey(
        PaymentMethod, verbose_name="forma de pagamento prevista", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    status = models.CharField(
        "status", max_length=20, choices=FinancialStatus.choices,
        default=FinancialStatus.PENDING, db_index=True,
    )
    notes = models.TextField("observacoes", blank=True)

    # Comissao (calculada quando a conta e quitada; ver apps.finance.services)
    professional_commission_amount = models.DecimalField(
        "valor do profissional", max_digits=10, decimal_places=2, null=True, blank=True,
    )
    clinic_amount = models.DecimalField(
        "valor da clinica", max_digits=10, decimal_places=2, null=True, blank=True,
    )

    class Meta:
        verbose_name = "conta a receber"
        verbose_name_plural = "contas a receber"
        ordering = ["due_date"]
        indexes = [
            models.Index(fields=["clinic", "status", "due_date"]),
            models.Index(fields=["clinic", "-service_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment"],
                condition=models.Q(appointment__isnull=False),
                name="uniq_receivable_per_appointment",
            )
        ]

    def __str__(self) -> str:
        alvo = self.patient.display_name if self.patient_id else self.description
        return f"{alvo} - R$ {self.net_amount}"

    @property
    def net_amount(self) -> Decimal:
        return (self.gross_amount or ZERO) - (self.discount or ZERO) + (self.addition or ZERO)

    @property
    def paid_amount(self) -> Decimal:
        totals = self.transactions.aggregate(
            income=models.Sum("amount", filter=models.Q(kind=FinancialTransaction.Kind.INCOME)),
            refund=models.Sum("amount", filter=models.Q(kind=FinancialTransaction.Kind.REFUND)),
        )
        return (totals["income"] or ZERO) - (totals["refund"] or ZERO)

    @property
    def balance(self) -> Decimal:
        return self.net_amount - self.paid_amount

    @property
    def is_overdue(self) -> bool:
        return (
            self.status in (FinancialStatus.PENDING, FinancialStatus.PARTIAL)
            and self.due_date < timezone.localdate()
        )


class PayableAccount(TenantModel):
    """Conta a pagar (despesa da clinica)."""

    supplier_name = models.CharField("fornecedor", max_length=150)
    category = models.ForeignKey(
        FinancialCategory, verbose_name="categoria", on_delete=models.PROTECT,
        related_name="payables", limit_choices_to={"kind": FinancialCategory.Kind.EXPENSE},
    )
    cost_center = models.ForeignKey(
        CostCenter, verbose_name="centro de custo", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="payables",
    )
    description = models.CharField("descricao", max_length=200)
    issue_date = models.DateField("data de lancamento", default=timezone.localdate)
    due_date = models.DateField("data de vencimento")
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2)
    expected_payment_method = models.ForeignKey(
        PaymentMethod, verbose_name="forma de pagamento prevista", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    status = models.CharField(
        "status", max_length=20, choices=FinancialStatus.choices,
        default=FinancialStatus.PENDING, db_index=True,
    )
    attachment = models.ForeignKey(
        "documents.Document", verbose_name="comprovante", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    notes = models.TextField("observacoes", blank=True)

    class Meta:
        verbose_name = "conta a pagar"
        verbose_name_plural = "contas a pagar"
        ordering = ["due_date"]
        indexes = [
            models.Index(fields=["clinic", "status", "due_date"]),
            models.Index(fields=["clinic", "cost_center"]),
        ]

    def __str__(self) -> str:
        return f"{self.supplier_name} - R$ {self.amount}"

    @property
    def paid_amount(self) -> Decimal:
        total = self.transactions.filter(
            kind=FinancialTransaction.Kind.EXPENSE
        ).aggregate(total=models.Sum("amount"))["total"]
        return total or ZERO

    @property
    def balance(self) -> Decimal:
        return (self.amount or ZERO) - self.paid_amount

    @property
    def is_overdue(self) -> bool:
        return (
            self.status in (FinancialStatus.PENDING, FinancialStatus.PARTIAL)
            and self.due_date < timezone.localdate()
        )


class FinancialTransaction(TenantModel):
    """
    Ledger unico: todo pagamento (de receita ou despesa) e um lancamento
    aqui. E a fonte de verdade tanto dos "pagamentos parciais" quanto do
    Fluxo de Caixa (cronologico, com saldo corrente).
    """

    class Kind(models.TextChoices):
        INCOME = "income", "Entrada"
        EXPENSE = "expense", "Saida"
        REFUND = "refund", "Estorno"

    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, db_index=True)
    receivable = models.ForeignKey(
        ReceivableAccount, verbose_name="conta a receber", on_delete=models.CASCADE,
        null=True, blank=True, related_name="transactions",
    )
    payable = models.ForeignKey(
        PayableAccount, verbose_name="conta a pagar", on_delete=models.CASCADE,
        null=True, blank=True, related_name="transactions",
    )
    category = models.ForeignKey(
        FinancialCategory, verbose_name="categoria", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transactions",
    )
    cost_center = models.ForeignKey(
        CostCenter, verbose_name="centro de custo", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transactions",
    )
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2)
    method = models.ForeignKey(
        PaymentMethod, verbose_name="forma de pagamento", on_delete=models.PROTECT,
        related_name="transactions",
    )
    paid_at = models.DateTimeField("data/hora", default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="registrado por", on_delete=models.SET_NULL,
        null=True, related_name="+",
    )
    notes = models.CharField("observacoes", max_length=250, blank=True)

    class Meta:
        verbose_name = "lancamento financeiro"
        verbose_name_plural = "lancamentos financeiros"
        ordering = ["-paid_at"]
        indexes = [
            models.Index(fields=["clinic", "-paid_at"]),
            models.Index(fields=["clinic", "kind", "-paid_at"]),
        ]

    def __str__(self) -> str:
        sinal = "+" if self.kind == self.Kind.INCOME else "-"
        metodo = self.method.name if self.method_id else ""
        return f"{sinal} R$ {self.amount} ({metodo})"


class ProfessionalCommissionRule(TenantModel, ActiveStatusMixin):
    """
    Regra de comissao do profissional.

    Prioridade de resolucao ao calcular uma comissao:
    (profissional + servico) > (profissional) > (servico) > sem regra (0%).
    """

    professional = models.ForeignKey(
        "professionals.Professional", verbose_name="profissional", on_delete=models.CASCADE,
        null=True, blank=True, related_name="commission_rules",
        help_text="Vazio = regra generica aplicada a qualquer profissional.",
    )
    service = models.ForeignKey(
        "clinics.Service", verbose_name="servico", on_delete=models.CASCADE,
        null=True, blank=True, related_name="commission_rules",
        help_text="Vazio = regra generica aplicada a qualquer servico.",
    )
    percentage = models.DecimalField(
        "percentual (%)", max_digits=5, decimal_places=2, null=True, blank=True,
    )
    fixed_amount = models.DecimalField(
        "valor fixo (R$)", max_digits=10, decimal_places=2, null=True, blank=True,
    )

    class Meta:
        verbose_name = "regra de comissao"
        verbose_name_plural = "regras de comissao"
        ordering = ["professional__full_name", "service__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "professional", "service"],
                condition=models.Q(is_deleted=False),
                name="uniq_commission_rule_per_clinic",
            )
        ]

    def __str__(self) -> str:
        alvo = self.professional.display_name if self.professional_id else "Qualquer profissional"
        servico = self.service.name if self.service_id else "qualquer servico"
        valor = f"{self.percentage}%" if self.percentage else f"R$ {self.fixed_amount}"
        return f"{alvo} / {servico} - {valor}"

    def compute(self, net_amount: Decimal) -> Decimal:
        if self.fixed_amount is not None:
            return min(self.fixed_amount, net_amount)
        if self.percentage is not None:
            return (net_amount * self.percentage / Decimal("100")).quantize(Decimal("0.01"))
        return ZERO
