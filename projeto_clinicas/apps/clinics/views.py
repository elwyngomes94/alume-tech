"""Configuracoes da clinica e cadastros auxiliares (administrador local)."""
from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from apps.clinics.forms import (
    ClinicProfileForm,
    ClinicSettingsForm,
    InsurancePlanForm,
    RoomForm,
    ServiceForm,
    SpecialtyForm,
)
from apps.clinics.models import (
    ClinicSettings,
    InsurancePlan,
    Room,
    Service,
    Specialty,
)
from apps.clinics.modules import MODULE_CATALOG
from apps.core.mixins import ClinicViewMixin


class ClinicProfileView(ClinicViewMixin, UpdateView):
    form_class = ClinicProfileForm
    template_name = "clinics/clinic_profile.html"
    required_permission = "clinic.change"
    success_url = reverse_lazy("clinics:profile")

    def get_object(self, queryset=None):
        return self.request.clinic

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modules"] = [
            (MODULE_CATALOG.get(code, (code, ""))[0], MODULE_CATALOG.get(code, ("", ""))[1])
            for code in self.request.clinic.enabled_modules()
        ]
        return context

    def form_valid(self, form):
        messages.success(self.request, "Dados da clinica atualizados.")
        return super().form_valid(form)


class ClinicSettingsView(ClinicViewMixin, UpdateView):
    form_class = ClinicSettingsForm
    template_name = "clinics/clinic_settings.html"
    required_permission = "clinic.settings"
    success_url = reverse_lazy("clinics:settings")

    def get_object(self, queryset=None):
        settings_obj, _created = ClinicSettings.objects.get_or_create(clinic=self.request.clinic)
        return settings_obj

    def form_valid(self, form):
        messages.success(self.request, "Configuracoes salvas.")
        return super().form_valid(form)


class CatalogHomeView(ClinicViewMixin, TemplateView):
    template_name = "clinics/catalog_home.html"
    required_permission = "clinic.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "specialties": Specialty.objects.all()[:50],
                "services": Service.objects.select_related("specialty")[:50],
                "rooms": Room.objects.all()[:50],
                "insurances": InsurancePlan.objects.all()[:50],
            }
        )
        return context


class _CatalogCreateView(ClinicViewMixin, CreateView):
    template_name = "clinics/catalog_form.html"
    success_url = reverse_lazy("clinics:catalog")
    entity_label = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity_label"] = self.entity_label
        return context

    def form_valid(self, form):
        messages.success(self.request, f"{self.entity_label} salvo(a).")
        return super().form_valid(form)


class _CatalogUpdateView(ClinicViewMixin, UpdateView):
    template_name = "clinics/catalog_form.html"
    success_url = reverse_lazy("clinics:catalog")
    entity_label = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity_label"] = self.entity_label
        return context

    def form_valid(self, form):
        messages.success(self.request, f"{self.entity_label} atualizado(a).")
        return super().form_valid(form)


class SpecialtyCreateView(_CatalogCreateView):
    model = Specialty
    form_class = SpecialtyForm
    required_permission = "specialty.manage"
    entity_label = "Especialidade"


class SpecialtyUpdateView(_CatalogUpdateView):
    model = Specialty
    form_class = SpecialtyForm
    required_permission = "specialty.manage"
    entity_label = "Especialidade"


class ServiceCreateView(_CatalogCreateView):
    model = Service
    form_class = ServiceForm
    required_permission = "service.manage"
    entity_label = "Servico"


class ServiceUpdateView(_CatalogUpdateView):
    model = Service
    form_class = ServiceForm
    required_permission = "service.manage"
    entity_label = "Servico"


class RoomCreateView(_CatalogCreateView):
    model = Room
    form_class = RoomForm
    required_permission = "room.manage"
    entity_label = "Sala"


class RoomUpdateView(_CatalogUpdateView):
    model = Room
    form_class = RoomForm
    required_permission = "room.manage"
    entity_label = "Sala"


class InsuranceCreateView(_CatalogCreateView):
    model = InsurancePlan
    form_class = InsurancePlanForm
    required_permission = "insurance.manage"
    entity_label = "Convenio"


class InsuranceUpdateView(_CatalogUpdateView):
    model = InsurancePlan
    form_class = InsurancePlanForm
    required_permission = "insurance.manage"
    entity_label = "Convenio"


class CatalogDeleteView(ClinicViewMixin, View):
    """Exclusao logica de um item de cadastro auxiliar."""

    required_permission = "clinic.settings"
    MODELS = {
        "especialidade": (Specialty, "Especialidade"),
        "servico": (Service, "Servico"),
        "sala": (Room, "Sala"),
        "convenio": (InsurancePlan, "Convenio"),
    }

    def post(self, request, entity, pk):
        if entity not in self.MODELS:
            messages.error(request, "Cadastro invalido.")
            return redirect("clinics:catalog")
        model, label = self.MODELS[entity]
        obj = get_object_or_404(model.objects.all(), pk=pk)
        obj.delete(user=request.user)
        messages.success(request, f"{label} removido(a).")
        return redirect("clinics:catalog")


class BillingView(ClinicViewMixin, TemplateView):
    template_name = "clinics/billing.html"
    required_permission = "billing.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.billing.services import clinic_limits

        subscription = getattr(self.request.clinic, "subscription", None)
        context["subscription"] = subscription
        context["limits"] = clinic_limits(self.request.clinic)
        context["invoices"] = (
            subscription.invoices.all()[:12] if subscription is not None else []
        )
        return context
