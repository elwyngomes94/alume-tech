"""Views de profissionais."""
from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import ClinicViewMixin
from apps.professionals.forms import ProfessionalForm
from apps.professionals.models import Professional


class ProfessionalSearchView(ClinicViewMixin, View):
    """Autocomplete de profissionais usado na agenda (busca por nome/especialidade)."""

    required_permission = "professional.view"

    def get(self, request):
        term = request.GET.get("q", "").strip()
        queryset = Professional.objects.filter(is_active=True).prefetch_related("specialties")
        if len(term) >= 2:
            queryset = queryset.filter(
                Q(full_name__icontains=term)
                | Q(social_name__icontains=term)
                | Q(specialties__name__icontains=term)
            ).distinct()
        results = [
            {
                "id": str(professional.pk),
                "text": professional.display_name,
                "detail": professional.specialty_names or "-",
            }
            for professional in queryset.order_by("full_name")[:12]
        ]
        return JsonResponse({"results": results})


class ProfessionalListView(ClinicViewMixin, ListView):
    model = Professional
    template_name = "professionals/professional_list.html"
    context_object_name = "professionals"
    paginate_by = 25
    required_permission = "professional.view"

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related("specialties").order_by("full_name")
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search)
                | Q(social_name__icontains=search)
                | Q(registry_number__icontains=search)
            )
        specialty = self.request.GET.get("specialty", "")
        if specialty:
            queryset = queryset.filter(specialties__id=specialty)
        active = self.request.GET.get("active", "")
        if active in ("0", "1"):
            queryset = queryset.filter(is_active=active == "1")
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.clinics.models import Specialty

        context["specialties"] = Specialty.objects.filter(is_active=True)
        return context


class ProfessionalDetailView(ClinicViewMixin, DetailView):
    model = Professional
    template_name = "professionals/professional_detail.html"
    context_object_name = "professional"
    required_permission = "professional.view"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("user")
            .prefetch_related("specialties", "services", "rooms")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.scheduling.models import Appointment, ScheduleTemplate

        context["schedules"] = ScheduleTemplate.objects.filter(
            professional=self.object
        ).order_by("weekday", "start_time")
        context["next_appointments"] = (
            Appointment.objects.filter(professional=self.object)
            .select_related("patient", "service")
            .filter(status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED])
            .order_by("start_at")[:10]
        )
        return context


class ProfessionalCreateView(ClinicViewMixin, CreateView):
    model = Professional
    form_class = ProfessionalForm
    template_name = "professionals/professional_form.html"
    required_permission = "professional.add"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        provisional = form.ensure_user_access(self.object)
        if provisional:
            messages.success(
                self.request,
                f"Profissional cadastrado. Senha provisoria de acesso: {provisional}",
            )
        else:
            messages.success(self.request, "Profissional cadastrado.")
        return response

    def get_success_url(self):
        return reverse("professionals:detail", args=[self.object.pk])


class ProfessionalUpdateView(ClinicViewMixin, UpdateView):
    model = Professional
    form_class = ProfessionalForm
    template_name = "professionals/professional_form.html"
    required_permission = "professional.change"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        provisional = form.ensure_user_access(self.object)
        if provisional:
            messages.success(self.request, f"Acesso criado. Senha provisoria: {provisional}")
        else:
            messages.success(self.request, "Profissional atualizado.")
        return response

    def get_success_url(self):
        return reverse("professionals:detail", args=[self.object.pk])


class ProfessionalDeleteView(ClinicViewMixin, View):
    required_permission = "professional.delete"

    def post(self, request, pk):
        professional = get_object_or_404(Professional.objects.all(), pk=pk)
        professional.is_active = False
        professional.save(update_fields=["is_active", "updated_at"])
        professional.delete(user=request.user)
        messages.success(request, "Profissional desativado.")
        return redirect("professionals:list")
