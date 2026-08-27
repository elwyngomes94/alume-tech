"""Views do modulo de estoque."""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.mixins import ClinicViewMixin
from apps.inventory import services
from apps.inventory.forms import ProductForm, StockMovementForm
from apps.inventory.models import Product, StockMovement


class ProductListView(ClinicViewMixin, ListView):
    model = Product
    template_name = "inventory/product_list.html"
    context_object_name = "products"
    required_permission = "inventory.view"

    def get_queryset(self):
        queryset = super().get_queryset().order_by("name")
        term = self.request.GET.get("q", "").strip()
        if term:
            queryset = queryset.filter(Q(name__icontains=term) | Q(sku__icontains=term))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["low_count"] = (
            Product.objects.filter(is_active=True).filter(current_stock__lt=F("minimum_stock")).count()
        )
        context["can_manage"] = self.request.user.has_clinic_perm(
            "inventory.manage", self.request.clinic
        )
        return context


class ProductCreateView(ClinicViewMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/product_form.html"
    required_permission = "inventory.manage"
    success_url = reverse_lazy("inventory:product-list")

    def form_valid(self, form):
        messages.success(self.request, "Produto cadastrado.")
        return super().form_valid(form)


class ProductUpdateView(ClinicViewMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/product_form.html"
    required_permission = "inventory.manage"
    success_url = reverse_lazy("inventory:product-list")

    def form_valid(self, form):
        messages.success(self.request, "Produto atualizado.")
        return super().form_valid(form)


class StockEntryView(ClinicViewMixin, View):
    """Registra entrada de estoque (compra, ajuste, doacao etc.)."""

    required_permission = "inventory.manage"

    def get(self, request, pk):
        product = get_object_or_404(Product.objects.all(), pk=pk)
        return render(
            request,
            "inventory/movement_form.html",
            {"product": product, "form": StockMovementForm(), "kind": "entry"},
        )

    def post(self, request, pk):
        product = get_object_or_404(Product.objects.all(), pk=pk)
        form = StockMovementForm(request.POST)
        if form.is_valid():
            try:
                services.register_entry(
                    product,
                    quantity=form.cleaned_data["quantity"],
                    unit_cost=form.cleaned_data.get("unit_cost"),
                    reason=form.cleaned_data.get("reason", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    user=request.user,
                )
                messages.success(request, "Entrada de estoque registrada.")
                return redirect("inventory:product-list")
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
        return render(
            request,
            "inventory/movement_form.html",
            {"product": product, "form": form, "kind": "entry"},
        )


class StockExitView(ClinicViewMixin, View):
    """Registra saida de estoque (uso, venda, perda etc.)."""

    required_permission = "inventory.manage"

    def get(self, request, pk):
        product = get_object_or_404(Product.objects.all(), pk=pk)
        return render(
            request,
            "inventory/movement_form.html",
            {"product": product, "form": StockMovementForm(), "kind": "exit"},
        )

    def post(self, request, pk):
        product = get_object_or_404(Product.objects.all(), pk=pk)
        form = StockMovementForm(request.POST)
        if form.is_valid():
            try:
                services.register_exit(
                    product,
                    quantity=form.cleaned_data["quantity"],
                    reason=form.cleaned_data.get("reason", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    user=request.user,
                )
                messages.success(request, "Saida de estoque registrada.")
                return redirect("inventory:product-list")
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
        return render(
            request,
            "inventory/movement_form.html",
            {"product": product, "form": form, "kind": "exit"},
        )


class StockMovementListView(ClinicViewMixin, ListView):
    model = StockMovement
    template_name = "inventory/movement_list.html"
    context_object_name = "movements"
    required_permission = "inventory.view"
    paginate_by = 50

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("product", "created_by")
            .order_by("-moved_at")
        )
