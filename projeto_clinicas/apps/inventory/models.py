"""
Estoque da clinica: produtos e movimentacoes (entrada/saida).

Segue o mesmo padrao do financeiro (``apps.finance``): ``TenantModel``
garante isolamento por clinica automatico e falha fechado. ``current_stock``
e denormalizado no produto (atualizado por ``apps.inventory.services``) para
listagens rapidas sem precisar somar o historico de movimentacoes a cada
consulta.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import ActiveStatusMixin, TenantModel

ZERO = Decimal("0")


class Product(TenantModel, ActiveStatusMixin):
    name = models.CharField("nome", max_length=160)
    sku = models.CharField("codigo/SKU", max_length=60, blank=True)
    unit = models.CharField("unidade", max_length=20, default="un")
    category = models.CharField("categoria", max_length=80, blank=True)
    minimum_stock = models.DecimalField(
        "estoque minimo", max_digits=10, decimal_places=2, default=ZERO
    )
    current_stock = models.DecimalField(
        "estoque atual", max_digits=10, decimal_places=2, default=ZERO
    )
    cost_price = models.DecimalField(
        "preco de custo", max_digits=10, decimal_places=2, default=ZERO
    )
    sale_price = models.DecimalField(
        "preco de venda", max_digits=10, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("observacoes", blank=True)

    class Meta:
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "sku"],
                condition=models.Q(is_deleted=False) & ~models.Q(sku=""),
                name="uniq_product_sku_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_below_minimum(self) -> bool:
        return self.current_stock < self.minimum_stock


class StockMovement(TenantModel):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada"
        EXIT = "exit", "Saida"

    product = models.ForeignKey(
        Product, verbose_name="produto", on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices)
    quantity = models.DecimalField("quantidade", max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(
        "custo unitario", max_digits=10, decimal_places=2, null=True, blank=True
    )
    reason = models.CharField("motivo", max_length=160, blank=True)
    notes = models.TextField("observacoes", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    moved_at = models.DateTimeField("data/hora", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "movimentacao de estoque"
        verbose_name_plural = "movimentacoes de estoque"
        ordering = ["-moved_at"]
        indexes = [models.Index(fields=["clinic", "-moved_at"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} - {self.product} ({self.quantity})"
