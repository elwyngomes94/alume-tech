"""Formularios de paciente."""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.forms import BootstrapFormMixin
from apps.clinics.models import InsurancePlan
from apps.core.validators import digits
from apps.patients.models import Patient, PatientAddress, PatientContact


class PatientForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "full_name",
            "social_name",
            "cpf",
            "rg",
            "birth_date",
            "gender",
            "marital_status",
            "occupation",
            "email",
            "phone",
            "mobile",
            "whatsapp",
            "blood_type",
            "allergies",
            "chronic_conditions",
            "continuous_medications",
            "health_notes",
            "insurance",
            "insurance_number",
            "guardian_name",
            "guardian_document",
            "guardian_phone",
            "guardian_relationship",
            "referral_source",
            "status",
            "notes",
            "photo",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "allergies": forms.Textarea(attrs={"rows": 2}),
            "chronic_conditions": forms.Textarea(attrs={"rows": 2}),
            "continuous_medications": forms.Textarea(attrs={"rows": 2}),
            "health_notes": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        self.clinic = clinic
        super().__init__(*args, **kwargs)
        # Convenios sempre restritos a clinica ativa
        self.fields["insurance"].queryset = InsurancePlan.objects.filter(is_active=True)

    def clean_cpf(self):
        cpf = self.cleaned_data.get("cpf", "").strip()
        if not cpf:
            return ""
        queryset = Patient.objects.filter(cpf=cpf)
        if self.instance.is_saved:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise ValidationError("Ja existe um paciente com este CPF nesta clinica.")
        return cpf

    def clean(self):
        cleaned = super().clean()
        birth_date = cleaned.get("birth_date")
        if birth_date:
            from django.utils import timezone

            if birth_date > timezone.localdate():
                self.add_error("birth_date", "Data de nascimento no futuro.")
        if not any(
            [cleaned.get("mobile"), cleaned.get("phone"), cleaned.get("email")]
        ):
            raise ValidationError("Informe ao menos um contato (celular, telefone ou e-mail).")
        return cleaned


class PatientSelfUpdateForm(BootstrapFormMixin, forms.ModelForm):
    """Campos que o proprio paciente pode atualizar no portal."""

    class Meta:
        model = Patient
        fields = ["social_name", "email", "phone", "mobile", "whatsapp", "occupation"]


class PatientAddressForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PatientAddress
        fields = [
            "kind",
            "postal_code",
            "street",
            "number",
            "complement",
            "district",
            "city",
            "state",
            "is_primary",
        ]

    def clean_postal_code(self):
        value = self.cleaned_data.get("postal_code", "")
        raw = digits(value)
        return f"{raw[:5]}-{raw[5:]}" if len(raw) == 8 else value


class PatientContactForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PatientContact
        fields = ["name", "relationship", "phone", "email", "is_emergency", "notes"]


PatientAddressFormSet = forms.inlineformset_factory(
    Patient, PatientAddress, form=PatientAddressForm, extra=1, can_delete=True
)
PatientContactFormSet = forms.inlineformset_factory(
    Patient, PatientContact, form=PatientContactForm, extra=1, can_delete=True
)
