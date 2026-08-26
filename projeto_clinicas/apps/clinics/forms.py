"""Formularios de clinica e cadastros auxiliares."""
from __future__ import annotations

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.clinics.models import (
    Clinic,
    ClinicSettings,
    InsurancePlan,
    Room,
    Service,
    Specialty,
)
from apps.clinics.modules import MODULE_CATALOG


class ClinicForm(BootstrapFormMixin, forms.ModelForm):
    """Cadastro completo da clinica (usado pelo SUPERADMIN)."""

    modules = forms.MultipleChoiceField(
        label="Modulos habilitados",
        required=False,
        choices=[(code, f"{label} - {desc}") for code, (label, desc) in MODULE_CATALOG.items()],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Clinic
        fields = [
            "legal_name",
            "trade_name",
            "document",
            "clinic_type",
            "logo",
            "organization",
            "address",
            "address_number",
            "address_complement",
            "district",
            "city",
            "state",
            "postal_code",
            "phone",
            "whatsapp",
            "email",
            "website",
            "responsible_name",
            "responsible_document",
            "professional_registry",
            "status",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_saved:
            self.fields["modules"].initial = self.instance.modules or []
        self.fields["organization"].required = False

    def save(self, commit=True):
        clinic = super().save(commit=False)
        selected = list(self.cleaned_data.get("modules") or [])
        if selected:
            clinic.modules = selected
        if commit:
            clinic.save()
        return clinic


class ClinicProfileForm(BootstrapFormMixin, forms.ModelForm):
    """Dados que o administrador local pode editar na propria clinica."""

    class Meta:
        model = Clinic
        fields = [
            "trade_name",
            "logo",
            "address",
            "address_number",
            "address_complement",
            "district",
            "city",
            "state",
            "postal_code",
            "phone",
            "whatsapp",
            "email",
            "website",
            "responsible_name",
            "professional_registry",
        ]


class ClinicSettingsForm(BootstrapFormMixin, forms.ModelForm):
    working_days = forms.MultipleChoiceField(
        label="Dias de funcionamento",
        required=False,
        choices=[
            (0, "Segunda"), (1, "Terca"), (2, "Quarta"), (3, "Quinta"),
            (4, "Sexta"), (5, "Sabado"), (6, "Domingo"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ClinicSettings
        fields = [
            "primary_color",
            "secondary_color",
            "appointment_duration",
            "opening_time",
            "closing_time",
            "allow_overbooking",
            "allow_patient_scheduling",
            "patient_cancel_hours",
            "notify_email",
            "notify_whatsapp",
            "notify_sms",
            "reminder_hours_before",
            "record_lock_hours",
            "require_photo_consent",
            "data_retention_years",
        ]
        widgets = {
            "primary_color": forms.TextInput(attrs={"type": "color"}),
            "secondary_color": forms.TextInput(attrs={"type": "color"}),
            "opening_time": forms.TimeInput(attrs={"type": "time"}),
            "closing_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_saved:
            self.fields["working_days"].initial = [
                str(day) for day in (self.instance.working_days or [])
            ]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.working_days = [int(day) for day in self.cleaned_data.get("working_days") or []]
        if commit:
            obj.save()
        return obj


class SpecialtyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Specialty
        fields = ["name", "description", "color", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "color": forms.TextInput(attrs={"type": "color"}),
        }


class ServiceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "name",
            "code",
            "specialty",
            "duration_minutes",
            "price",
            "requires_room",
            "description",
            "is_active",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["specialty"].queryset = Specialty.objects.filter(is_active=True)
        self.fields["specialty"].required = False


class RoomForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "identifier", "capacity", "notes", "is_active"]


class InsurancePlanForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InsurancePlan
        fields = ["name", "registry_code", "contact", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}
