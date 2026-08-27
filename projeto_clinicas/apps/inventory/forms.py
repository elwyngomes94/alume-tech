"""Formularios do modulo de estoque."""
from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.inventory.models import Product


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "sku", "unit", "category", "minimum_stock",
            "cost_price", "sale_price", "notes", "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class StockMovementForm(BootstrapFormMixin, forms.Form):
    quantity = forms.DecimalField(
        label="Quantidade", min_value=Decimal("0.01"), max_digits=10, decimal_places=2
    )
    unit_cost = forms.DecimalField(
        label="Custo unitario", required=False, max_digits=10, decimal_places=2
    )
    reason = forms.CharField(label="Motivo", max_length=160, required=False)
    notes = forms.CharField(
        label="Observacoes", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
