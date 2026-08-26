"""Formularios de profissionais."""
from __future__ import annotations

import secrets

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.accounts.models import User
from apps.accounts.permissions import Roles
from apps.clinics.models import Room, Service, Specialty
from apps.professionals.models import Professional
from apps.tenants.models import ClinicMembership


class ProfessionalForm(BootstrapFormMixin, forms.ModelForm):
    create_access = forms.BooleanField(
        label="Criar acesso ao sistema para este profissional",
        required=False,
        initial=True,
        help_text="Gera um usuario com perfil PROFISSIONAL vinculado a esta clinica.",
    )

    class Meta:
        model = Professional
        fields = [
            "full_name",
            "social_name",
            "cpf",
            "birth_date",
            "email",
            "phone",
            "photo",
            "council",
            "registry_number",
            "registry_state",
            "specialties",
            "subspecialty",
            "services",
            "rooms",
            "appointment_duration",
            "accepts_online_scheduling",
            "biography",
            "is_active",
            "notes",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "biography": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "specialties": forms.CheckboxSelectMultiple,
            "services": forms.CheckboxSelectMultiple,
            "rooms": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, clinic=None, **kwargs):
        self.clinic = clinic
        super().__init__(*args, **kwargs)
        # Todos os relacionamentos ficam restritos a clinica ativa.
        self.fields["specialties"].queryset = Specialty.objects.filter(is_active=True)
        self.fields["services"].queryset = Service.objects.filter(is_active=True)
        self.fields["rooms"].queryset = Room.objects.filter(is_active=True)
        if self.instance.is_saved and self.instance.user_id:
            self.fields["create_access"].initial = False
            self.fields["create_access"].disabled = True
            self.fields["create_access"].help_text = "Este profissional ja possui acesso."

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("create_access") and not cleaned.get("email"):
            self.add_error("email", "Informe o e-mail para criar o acesso ao sistema.")
        return cleaned

    def ensure_user_access(self, professional: Professional):
        """Cria (se necessario) o usuario e o vinculo do profissional."""
        if not self.cleaned_data.get("create_access") or professional.user_id:
            return None
        email = self.cleaned_data["email"].lower()
        user = User.objects.filter(email__iexact=email).first()
        provisional = None
        if user is None:
            provisional = secrets.token_urlsafe(10)
            user = User.objects.create_user(
                email=email,
                password=provisional,
                full_name=professional.full_name,
                role=Roles.PROFESSIONAL,
                must_change_password=True,
            )
        professional.user = user
        professional.save(update_fields=["user", "updated_at"])
        ClinicMembership.all_objects.update_or_create(
            user=user,
            clinic=professional.clinic,
            defaults={
                "role": Roles.PROFESSIONAL,
                "is_active": True,
                "is_deleted": False,
                "job_title": professional.subspecialty or "Profissional",
            },
        )
        return provisional
