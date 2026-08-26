"""Formularios das automacoes."""
from __future__ import annotations

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.automation.models import AutomationSettings


class AutomationSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AutomationSettings
        fields = ["waiting_list_auto_invite", "auto_generate_receipt", "financial_webhook_enabled"]
