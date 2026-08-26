"""Formularios do prontuario, incluindo o formulario dinamico por modelo."""
from __future__ import annotations

import json
from typing import Any, Dict

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.forms import BootstrapFormMixin
from apps.medical_records.models import (
    MedicalRecordEntry,
    Prescription,
    RecordTemplate,
    VitalSigns,
)
from apps.professionals.models import Professional

#: Nomes de campo do schema dinamico que ganham autocomplete de CID-10.
CID_FIELD_NAMES = {"cid", "diagnostico", "diagnosis", "cid10"}

FIELD_BUILDERS = {
    "text": lambda field: forms.CharField(max_length=250, required=field.get("required", False)),
    "textarea": lambda field: forms.CharField(
        required=field.get("required", False), widget=forms.Textarea(attrs={"rows": 3})
    ),
    "number": lambda field: forms.DecimalField(required=field.get("required", False)),
    "date": lambda field: forms.DateField(
        required=field.get("required", False), widget=forms.DateInput(attrs={"type": "date"})
    ),
    "select": lambda field: forms.ChoiceField(
        required=field.get("required", False),
        choices=[("", "---")] + [(opt, opt) for opt in field.get("options", [])],
    ),
    "multiselect": lambda field: forms.MultipleChoiceField(
        required=field.get("required", False),
        choices=[(opt, opt) for opt in field.get("options", [])],
        widget=forms.CheckboxSelectMultiple,
    ),
    "checkbox": lambda field: forms.BooleanField(required=False),
}


class DynamicRecordEntryForm(BootstrapFormMixin, forms.Form):
    """
    Formulario gerado em tempo de execucao a partir do schema do modelo.

    Mantem o prontuario adaptavel ao tipo de clinica (medica, fisioterapia,
    estetica, nutricao...) sem criar tabelas especificas por profissao.
    """

    def __init__(self, *args, template: RecordTemplate, initial_data: Dict[str, Any] = None,
                 **kwargs):
        self.template = template
        super().__init__(*args, **kwargs)
        initial_data = initial_data or {}
        self.section_map = {}
        for section_title, field in template.fields():
            name = field.get("name")
            if not name:
                continue
            builder = FIELD_BUILDERS.get(field.get("type", "textarea"), FIELD_BUILDERS["textarea"])
            form_field = builder(field)
            form_field.label = field.get("label", name)
            form_field.help_text = field.get("help", "")
            form_field.initial = initial_data.get(name)
            if field.get("type", "textarea") == "text" and name.lower() in CID_FIELD_NAMES:
                form_field.widget.attrs["data-cid-search"] = "1"
                form_field.widget.attrs["autocomplete"] = "off"
            self.fields[name] = form_field
            self.section_map.setdefault(section_title, []).append(name)
        # aplica classes do Bootstrap depois de montar os campos dinamicos
        for form_field in self.fields.values():
            widget = form_field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")

    def sections(self):
        """Itera as secoes com os campos ja renderizaveis no template."""
        for title, names in self.section_map.items():
            yield title, [self[name] for name in names]

    def to_data(self) -> Dict[str, Any]:
        payload = {}
        for name, value in self.cleaned_data.items():
            if hasattr(value, "isoformat"):
                payload[name] = value.isoformat()
            elif isinstance(value, (list, tuple)):
                payload[name] = list(value)
            elif value is None:
                payload[name] = ""
            else:
                payload[name] = str(value) if not isinstance(value, bool) else value
        return payload


class RecordEntryMetaForm(BootstrapFormMixin, forms.ModelForm):
    """Dados gerais do atendimento (profissional, data, modelo)."""

    class Meta:
        model = MedicalRecordEntry
        fields = ["professional", "template", "title", "attended_at"]
        widgets = {"attended_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["template"].queryset = RecordTemplate.objects.filter(is_active=True)
        self.fields["attended_at"].input_formats = ["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"]
        if user is not None:
            own = Professional.objects.filter(user=user, is_active=True).first()
            if own is not None:
                self.fields["professional"].initial = own


class RecordTemplateForm(BootstrapFormMixin, forms.ModelForm):
    schema_json = forms.CharField(
        label="Estrutura (JSON)",
        widget=forms.Textarea(attrs={"rows": 16, "class": "form-control font-monospace"}),
        help_text='Formato: {"sections": [{"title": "...", "fields": [...]}]}',
    )

    class Meta:
        model = RecordTemplate
        fields = ["name", "description", "specialty", "is_default", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.clinics.models import Specialty

        self.fields["specialty"].queryset = Specialty.objects.filter(is_active=True)
        # "instance.pk" nao serve de indicador aqui: o UUIDField tem
        # default=uuid.uuid4, entao uma instancia nova ja nasce com pk.
        if not self.instance._state.adding:
            self.fields["schema_json"].initial = json.dumps(
                self.instance.schema, indent=2, ensure_ascii=False
            )

    def clean_schema_json(self):
        raw = self.cleaned_data["schema_json"]
        try:
            schema = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"JSON invalido: {exc}") from exc
        sections = schema.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValidationError("O modelo precisa de ao menos uma secao.")
        for section in sections:
            fields = section.get("fields")
            if not isinstance(fields, list):
                raise ValidationError("Cada secao precisa de uma lista 'fields'.")
            for field in fields:
                if not field.get("name") or not field.get("label"):
                    raise ValidationError("Cada campo precisa de 'name' e 'label'.")
                kind = field.get("type", "textarea")
                if kind not in FIELD_BUILDERS:
                    raise ValidationError(f"Tipo de campo nao suportado: {kind}")
        return schema

    def save(self, commit=True):
        template = super().save(commit=False)
        template.schema = self.cleaned_data["schema_json"]
        if commit:
            template.save()
        return template


class VitalSignsForm(BootstrapFormMixin, forms.ModelForm):
    """Sinais vitais do atendimento -- todos os campos opcionais."""

    class Meta:
        model = VitalSigns
        fields = [
            "systolic_pressure", "diastolic_pressure", "heart_rate", "respiratory_rate",
            "temperature", "oxygen_saturation", "weight_kg", "height_cm", "glucose", "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class PrescriptionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Prescription
        fields = [
            "kind",
            "content",
            "instructions",
            "valid_until",
            "released_to_patient",
        ]
        widgets = {
            "content": forms.Textarea(attrs={"rows": 6}),
            "instructions": forms.Textarea(attrs={"rows": 3}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
        }


class SignEntryForm(BootstrapFormMixin, forms.Form):
    confirm = forms.BooleanField(
        label="Confirmo que as informacoes registradas estao corretas e assumo a "
        "responsabilidade tecnica por este registro.",
        required=True,
    )


class ReviseEntryForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        label="Motivo da retificacao",
        max_length=250,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
