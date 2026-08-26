"""Formularios de documentos."""
from __future__ import annotations

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.documents.models import Document, DocumentCategory
from apps.patients.models import Patient


class DocumentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            "patient",
            "category",
            "title",
            "description",
            "file",
            "issued_at",
            "is_sensitive",
            "visible_to_patient",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "issued_at": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.all()
        self.fields["category"].queryset = DocumentCategory.objects.filter(is_active=True)
        self.fields["patient"].required = False
        if patient is not None:
            self.fields["patient"].initial = patient
            self.fields["patient"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        if category is not None and cleaned.get("visible_to_patient") is None:
            cleaned["visible_to_patient"] = category.visible_to_patient_default
        return cleaned


class DocumentCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DocumentCategory
        fields = [
            "name",
            "description",
            "is_clinical",
            "visible_to_patient_default",
            "is_active",
        ]
