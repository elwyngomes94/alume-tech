"""Regras de negocio do estoque: entrada e saida sempre atomicas."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import Product, StockMovement

ZERO = Decimal("0")


def register_entry(
    product: Product, *, quantity: Decimal, unit_cost: Optional[Decimal] = None,
    reason: str = "", notes: str = "", user=None, moved_at=None,
) -> StockMovement:
    if quantity is None or quantity <= ZERO:
        raise ValidationError("A quantidade deve ser maior que zero.")
    with transaction.atomic():
        movement = StockMovement.objects.create(
            clinic=product.clinic,
            product=product,
            kind=StockMovement.Kind.ENTRY,
            quantity=quantity,
            unit_cost=unit_cost,
            reason=reason,
            notes=notes,
            created_by=user,
            moved_at=moved_at or timezone.now(),
        )
        product.current_stock = product.current_stock + quantity
        product.save(update_fields=["current_stock", "updated_at"])
    return movement


def register_exit(
    product: Product, *, quantity: Decimal, reason: str = "", notes: str = "",
    user=None, moved_at=None,
) -> StockMovement:
    if quantity is None or quantity <= ZERO:
        raise ValidationError("A quantidade deve ser maior que zero.")
    if quantity > product.current_stock:
        raise ValidationError(
            f"Saida de {quantity} maior que o saldo disponivel ({product.current_stock})."
        )
    with transaction.atomic():
        movement = StockMovement.objects.create(
            clinic=product.clinic,
            product=product,
            kind=StockMovement.Kind.EXIT,
            quantity=quantity,
            reason=reason,
            notes=notes,
            created_by=user,
            moved_at=moved_at or timezone.now(),
        )
        product.current_stock = product.current_stock - quantity
        product.save(update_fields=["current_stock", "updated_at"])
    return movement
