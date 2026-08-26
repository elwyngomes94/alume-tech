"""Formularios de exames."""
from __future__ import annotations

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.examinations.models import (
    Examination,
    ExaminationRequest,
    ExaminationRequestItem,
    ExaminationResult,
)
from apps.patients.models import Patient
from apps.professionals.models import Professional


class ExaminationRequestForm(BootstrapFormMixin, forms.ModelForm):
    exams_text = forms.CharField(
        label="Exames solicitados",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Um exame por linha.",
    )

    class Meta:
        model = ExaminationRequest
        fields = [
            "patient",
            "professional",
            "clinical_indication",
            "priority",
            "observations",
            "released_to_patient",
        ]
        widgets = {
            "clinical_indication": forms.Textarea(attrs={"rows": 3}),
            "observations": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.all()
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        if patient is not None:
            self.fields["patient"].initial = patient
        if user is not None:
            own = Professional.objects.filter(user=user, is_active=True).first()
            if own is not None:
                self.fields["professional"].initial = own
        if self.instance.is_saved:
            self.fields["exams_text"].initial = "\n".join(
                item.name for item in self.instance.items.all()
            )

    def clean_exams_text(self):
        raw = self.cleaned_data["exams_text"]
        exams = [line.strip() for line in raw.splitlines() if line.strip()]
        if not exams:
            raise forms.ValidationError("Informe ao menos um exame.")
        return exams

    def save_items(self, request_obj: ExaminationRequest) -> None:
        ExaminationRequestItem.all_objects.filter(request=request_obj).delete()
        catalog = {
            item.name.lower(): item
            for item in Examination.objects.filter(is_active=True)
        }
        for name in self.cleaned_data["exams_text"]:
            ExaminationRequestItem.objects.create(
                clinic_id=request_obj.clinic_id,
                request=request_obj,
                name=name,
                examination=catalog.get(name.lower()),
            )


class ExaminationResultForm(BootstrapFormMixin, forms.ModelForm):
    file = forms.FileField(label="Arquivo do resultado", required=False)

    class Meta:
        model = ExaminationResult
        fields = ["item", "summary", "result_date", "is_abnormal", "released_to_patient"]
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 4}),
            "result_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, request_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_obj = request_obj
        if request_obj is not None:
            self.fields["item"].queryset = ExaminationRequestItem.objects.filter(
                request=request_obj
            )
        else:
            self.fields["item"].queryset = ExaminationRequestItem.objects.none()
        self.fields["item"].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("summary") and not cleaned.get("file"):
            raise forms.ValidationError("Anexe o arquivo ou descreva o resultado.")
        return cleaned


class ExaminationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Examination
        fields = ["name", "code", "category", "preparation", "is_active"]
        widgets = {"preparation": forms.Textarea(attrs={"rows": 2})}
