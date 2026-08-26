"""Planos, assinaturas e faturamento do SaaS."""
from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.clinics.modules import MODULE_CATALOG
from apps.core.models import ActiveStatusMixin, BaseModel


class Plan(BaseModel, ActiveStatusMixin):
    """Plano comercial do JJA System."""

    class Tier(models.TextChoices):
        BASIC = "basic", "Basico"
        PROFESSIONAL = "professional", "Profissional"
        PREMIUM = "premium", "Premium"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField("nome", max_length=80, unique=True)
    tier = models.CharField("nivel", max_length=20, choices=Tier.choices, default=Tier.BASIC)
    description = models.TextField("descricao", blank=True)
    monthly_price = models.DecimalField("mensalidade", max_digits=10, decimal_places=2,
                                        default=Decimal("0.00"))
    yearly_price = models.DecimalField("anuidade", max_digits=10, decimal_places=2,
                                       default=Decimal("0.00"))

    # Limites (0 = ilimitado)
    max_professionals = models.PositiveIntegerField("limite de profissionais", default=3)
    max_users = models.PositiveIntegerField("limite de usuarios", default=5)
    max_patients = models.PositiveIntegerField("limite de pacientes", default=500)
    max_storage_mb = models.PositiveIntegerField("armazenamento (MB)", default=2048)
    max_clinics = models.PositiveIntegerField("clinicas por organizacao", default=1)

    modules = models.JSONField("modulos incluidos", default=list, blank=True)
    supports_api = models.BooleanField("acesso a API", default=False)
    supports_mfa = models.BooleanField("MFA obrigatorio disponivel", default=True)
    priority_support = models.BooleanField("suporte prioritario", default=False)
    trial_days = models.PositiveIntegerField("dias de avaliacao", default=14)

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"
        ordering = ["monthly_price"]

    def __str__(self) -> str:
        return self.name

    @property
    def module_labels(self):
        return [MODULE_CATALOG.get(code, (code, ""))[0] for code in (self.modules or [])]

    def limit_for(self, resource: str) -> int:
        return {
            "professionals": self.max_professionals,
            "users": self.max_users,
            "patients": self.max_patients,
            "storage": self.max_storage_mb,
            "clinics": self.max_clinics,
        }.get(resource, 0)


class Subscription(BaseModel):
    """Assinatura de uma clinica a um plano."""

    class Status(models.TextChoices):
        TRIAL = "trial", "Avaliacao"
        ACTIVE = "active", "Ativa"
        PAST_DUE = "past_due", "Em atraso"
        CANCELED = "canceled", "Cancelada"

    class Cycle(models.TextChoices):
        MONTHLY = "monthly", "Mensal"
        YEARLY = "yearly", "Anual"

    clinic = models.OneToOneField(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="subscription",
        verbose_name="clinica",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions",
                             verbose_name="plano")
    status = models.CharField("status", max_length=20, choices=Status.choices,
                              default=Status.TRIAL, db_index=True)
    cycle = models.CharField("ciclo", max_length=20, choices=Cycle.choices, default=Cycle.MONTHLY)
    started_at = models.DateField("inicio", default=timezone.localdate)
    trial_ends_at = models.DateField("fim da avaliacao", null=True, blank=True)
    current_period_start = models.DateField("inicio do periodo", null=True, blank=True)
    current_period_end = models.DateField("fim do periodo", null=True, blank=True)
    canceled_at = models.DateField(null=True, blank=True)
    notes = models.TextField("observacoes", blank=True)

    class Meta:
        verbose_name = "assinatura"
        verbose_name_plural = "assinaturas"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.clinic} - {self.plan}"

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.ACTIVE, self.Status.TRIAL)

    @property
    def price(self) -> Decimal:
        return (
            self.plan.yearly_price if self.cycle == self.Cycle.YEARLY else self.plan.monthly_price
        )


class Invoice(BaseModel):
    """Fatura emitida para uma assinatura."""

    class Status(models.TextChoices):
        OPEN = "open", "Em aberto"
        PAID = "paid", "Paga"
        OVERDUE = "overdue", "Vencida"
        CANCELED = "canceled", "Cancelada"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="invoices"
    )
    number = models.CharField("numero", max_length=20, unique=True)
    reference_month = models.DateField("competencia")
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2)
    due_date = models.DateField("vencimento")
    status = models.CharField("status", max_length=20, choices=Status.choices,
                              default=Status.OPEN, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField("observacoes", max_length=250, blank=True)

    class Meta:
        verbose_name = "fatura"
        verbose_name_plural = "faturas"
        ordering = ["-reference_month"]

    def __str__(self) -> str:
        return f"Fatura {self.number}"

    @property
    def is_overdue(self) -> bool:
        return self.status == self.Status.OPEN and self.due_date < timezone.localdate()


class Payment(BaseModel):
    """
    Pagamento de uma fatura.

    O sistema opera sem gateway; a integracao futura apenas preenche
    ``gateway`` e ``external_id``.
    """

    class Method(models.TextChoices):
        PIX = "pix", "PIX"
        BOLETO = "boleto", "Boleto"
        CARD = "card", "Cartao"
        TRANSFER = "transfer", "Transferencia"
        MANUAL = "manual", "Baixa manual"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2)
    method = models.CharField("forma", max_length=20, choices=Method.choices,
                              default=Method.MANUAL)
    paid_at = models.DateTimeField("pago em", default=timezone.now)
    gateway = models.CharField("gateway", max_length=40, blank=True)
    external_id = models.CharField("id externo", max_length=120, blank=True)
    receipt = models.CharField("comprovante", max_length=180, blank=True)

    class Meta:
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        ordering = ["-paid_at"]

    def __str__(self) -> str:
        return f"{self.get_method_display()} - R$ {self.amount}"


class SystemExpense(BaseModel):
    """
    Despesa operacional da propria plataforma JJA System.

    Contrapartida das receitas de assinatura (``Payment``): junto formam a
    contabilidade do negocio SaaS, visivel apenas ao SUPERADMIN.
    """

    class Category(models.TextChoices):
        INFRASTRUCTURE = "infrastructure", "Infraestrutura/servidores"
        PAYROLL = "payroll", "Folha de pagamento"
        MARKETING = "marketing", "Marketing"
        SOFTWARE = "software", "Ferramentas e licencas"
        SUPPORT = "support", "Suporte"
        TAXES = "taxes", "Impostos"
        OTHER = "other", "Outros"

    category = models.CharField(
        "categoria", max_length=20, choices=Category.choices, default=Category.OTHER
    )
    description = models.CharField("descricao", max_length=200)
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2)
    expense_date = models.DateField("data")
    is_recurring = models.BooleanField("recorrente", default=False)
    notes = models.TextField("observacoes", blank=True)

    class Meta:
        verbose_name = "despesa do sistema"
        verbose_name_plural = "despesas do sistema"
        ordering = ["-expense_date"]

    def __str__(self) -> str:
        return f"{self.description} - R$ {self.amount}"
