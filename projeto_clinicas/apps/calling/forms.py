from django import forms

from apps.calling.models import CallPanelConfig


class CallPanelConfigForm(forms.ModelForm):
    class Meta:
        model = CallPanelConfig
        fields = ["ticket_prefix", "display_mode", "sound_enabled", "no_show_minutes"]
        widgets = {
            "ticket_prefix": forms.TextInput(attrs={"class": "form-control", "maxlength": 3}),
            "display_mode": forms.Select(attrs={"class": "form-select"}),
            "sound_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "no_show_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def clean_ticket_prefix(self):
        prefix = self.cleaned_data["ticket_prefix"].strip().upper()
        if not prefix.isalpha():
            raise forms.ValidationError("Use apenas letras (ex.: A, B, TR).")
        return prefix
