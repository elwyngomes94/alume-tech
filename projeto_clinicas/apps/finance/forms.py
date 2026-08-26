"""Formularios do financeiro da clinica."""
from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.clinics.models import Service
from apps.core.validators import validate_upload
from apps.finance.models import (
    CostCenter,
    FinancialCategory,
    PaymentMethod,
    PayableAccount,
    ProfessionalCommissionRule,
    ReceivableAccount,
)
from apps.patients.models import Patient
from apps.professionals.models import Professional


class ReceivableForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ReceivableAccount
        fields = [
            "patient", "professional", "service", "category", "description",
            "service_date", "due_date", "gross_amount", "discount", "addition",
            "expected_payment_method", "notes",
        ]
        widgets = {
            "service_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.all()
        self.fields["patient"].required = False
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["professional"].required = False
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["service"].required = False
        self.fields["category"].queryset = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.INCOME, is_active=True
        )
        self.fields["expected_payment_method"].queryset = PaymentMethod.objects.filter(
            is_active=True
        )
        self.fields["expected_payment_method"].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("patient") and not cleaned.get("description"):
            raise forms.ValidationError(
                "Informe o paciente ou uma descricao para identificar o lancamento."
            )
        gross = cleaned.get("gross_amount") or Decimal("0")
        discount = cleaned.get("discount") or Decimal("0")
        addition = cleaned.get("addition") or Decimal("0")
        if discount > gross + addition:
            self.add_error("discount", "O desconto nao pode ser maior que o valor bruto.")
        return cleaned


class PayableForm(BootstrapFormMixin, forms.ModelForm):
    receipt_file = forms.FileField(
        label="Comprovante", required=False, validators=[validate_upload],
        help_text="PDF ou imagem do comprovante (opcional).",
    )

    class Meta:
        model = PayableAccount
        fields = [
            "supplier_name", "category", "cost_center", "description",
            "issue_date", "due_date", "amount", "expected_payment_method", "notes",
        ]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.EXPENSE, is_active=True
        )
        self.fields["cost_center"].queryset = CostCenter.objects.filter(is_active=True)
        self.fields["cost_center"].required = False
        self.fields["expected_payment_method"].queryset = PaymentMethod.objects.filter(
            is_active=True
        )
        self.fields["expected_payment_method"].required = False


class RegisterPaymentForm(BootstrapFormMixin, forms.Form):
    amount = forms.DecimalField(label="Valor pago", min_value=Decimal("0.01"), decimal_places=2)
    method = forms.ModelChoiceField(label="Forma de pagamento", queryset=PaymentMethod.objects.none())
    paid_at = forms.DateField(label="Data do pagamento", widget=forms.DateInput(attrs={"type": "date"}))
    notes = forms.CharField(label="Observacoes", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = PaymentMethod.objects.filter(is_active=True)


class ManualTransactionForm(BootstrapFormMixin, forms.Form):
    kind = forms.ChoiceField(label="Tipo", choices=[("income", "Entrada"), ("expense", "Saida")])
    amount = forms.DecimalField(label="Valor", min_value=Decimal("0.01"), decimal_places=2)
    method = forms.ModelChoiceField(label="Forma de pagamento", queryset=PaymentMethod.objects.none())
    category = forms.ModelChoiceField(
        label="Categoria", queryset=FinancialCategory.objects.none(), required=False,
    )
    cost_center = forms.ModelChoiceField(
        label="Centro de custo", queryset=CostCenter.objects.none(), required=False,
    )
    paid_at = forms.DateField(label="Data", widget=forms.DateInput(attrs={"type": "date"}))
    notes = forms.CharField(label="Observacoes", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = PaymentMethod.objects.filter(is_active=True)
        self.fields["category"].queryset = FinancialCategory.objects.filter(is_active=True)
        self.fields["cost_center"].queryset = CostCenter.objects.filter(is_active=True)


class CancelForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(label="Motivo do cancelamento", widget=forms.Textarea(attrs={"rows": 2}))


class PaymentMethodForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "kind", "is_active"]


class FinancialCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = FinancialCategory
        fields = ["name", "kind", "description", "is_active"]


class CostCenterForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CostCenter
        fields = ["name", "description", "is_active"]


class CommissionRuleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProfessionalCommissionRule
        fields = ["professional", "service", "percentage", "fixed_amount", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["professional"].required = False
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["service"].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("percentage") and not cleaned.get("fixed_amount"):
            raise forms.ValidationError("Informe um percentual ou um valor fixo de comissao.")
        if cleaned.get("percentage") and cleaned.get("fixed_amount"):
            raise forms.ValidationError("Informe apenas percentual OU valor fixo, nao os dois.")
        return cleaned
