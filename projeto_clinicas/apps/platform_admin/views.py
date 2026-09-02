"""
Painel do SUPERADMIN (/platform/).

Todas as consultas globais entram explicitamente em
:func:`apps.core.tenancy.unscoped` e qualquer acesso a dados de uma clinica e
registrado na auditoria como ``PLATFORM_ACCESS``.
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.accounts.forms import AdminSetPasswordForm, BootstrapFormMixin
from apps.accounts.models import LoginAttempt, User
from apps.accounts.permissions import Roles
from apps.audit.models import AuditAction, AuditLog
from apps.audit.services import log_action
from apps.billing.models import Invoice, Plan, Subscription, SystemExpense
from apps.clinics.forms import ClinicForm
from apps.clinics.models import Clinic
from apps.clinics.modules import ClinicType
from apps.core.mixins import SuperadminRequiredMixin
from apps.core.tenancy import tenant_context, unscoped
from apps.core.utils import period_range
from apps.platform_admin import services
from apps.tenants.middleware import SESSION_CLINIC_KEY
from apps.tenants.models import ClinicMembership, Organization


class UnscopedMixin(SuperadminRequiredMixin):
    """Executa a view inteira em contexto global, com justificativa registrada."""

    unscoped_reason = "painel da plataforma"

    def dispatch(self, request, *args, **kwargs):
        with unscoped(self.unscoped_reason):
            return super().dispatch(request, *args, **kwargs)


class PlatformDashboardView(UnscopedMixin, TemplateView):
    template_name = "platform/dashboard.html"
    unscoped_reason = "dashboard global"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.request.GET.get("period", "30d")
        start, end = period_range(period, self.request.GET.get("start", ""),
                                  self.request.GET.get("end", ""))
        metrics = services.platform_metrics(start, end)

        from django.db.models.functions import TruncMonth

        growth = list(
            Clinic.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(total=Count("id"))
            .order_by("month")
        )

        type_labels = dict(ClinicType.CHOICES)
        context.update(
            {
                "metrics": metrics,
                "period": period,
                "start": start,
                "end": end,
                "recent_clinics": Clinic.objects.order_by("-created_at")[:8],
                "recent_audit": AuditLog.objects.select_related("user", "clinic")[:12],
                "failed_logins": LoginAttempt.objects.filter(successful=False)[:10],
                "chart_type_labels": [
                    type_labels.get(item["clinic_type"], item["clinic_type"])
                    for item in metrics["by_type"]
                ],
                "chart_type_values": [item["total"] for item in metrics["by_type"]],
                "chart_growth_labels": [item["month"].strftime("%m/%Y") for item in growth],
                "chart_growth_values": [item["total"] for item in growth],
            }
        )

        from apps.automation.models import AutomationExecution

        context["automation_totals"] = {
            "total": AutomationExecution.objects.count(),
            "success": AutomationExecution.objects.filter(
                status=AutomationExecution.Status.SUCCESS
            ).count(),
            "failed": AutomationExecution.objects.filter(
                status=AutomationExecution.Status.FAILED
            ).count(),
        }
        context["automation_by_type"] = list(
            AutomationExecution.objects.values("automation__name", "status")
            .annotate(total=Count("id"))
            .order_by("automation__name")
        )
        return context


class ClinicListView(UnscopedMixin, ListView):
    model = Clinic
    template_name = "platform/clinic_list.html"
    context_object_name = "clinics"
    paginate_by = 25
    unscoped_reason = "listagem de clinicas"

    def get_queryset(self):
        from django.db.models import Max, OuterRef, Subquery

        last_activity = AuditLog.objects.filter(clinic=OuterRef("pk")).order_by(
            "-created_at"
        ).values("created_at")[:1]

        queryset = (
            Clinic.objects.select_related("organization", "subscription__plan")
            .annotate(
                total_users=Count("memberships", distinct=True),
                total_patients=Count("patients_patient_set", distinct=True),
                last_activity=Subquery(last_activity),
            )
        )
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(trade_name__icontains=search)
                | Q(legal_name__icontains=search)
                | Q(document__icontains=search)
                | Q(city__icontains=search)
            )
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        clinic_type = self.request.GET.get("type", "")
        if clinic_type:
            queryset = queryset.filter(clinic_type=clinic_type)
        plan = self.request.GET.get("plan", "")
        if plan:
            queryset = queryset.filter(subscription__plan_id=plan)
        return queryset.order_by("trade_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Clinic.Status.choices
        context["type_choices"] = ClinicType.CHOICES
        context["plan_choices"] = Plan.objects.filter(is_active=True).order_by("name")

        status_counts = dict(
            Clinic.objects.values_list("status").annotate(total=Count("id"))
        )
        context["summary"] = {
            "total": sum(status_counts.values()),
            "active": status_counts.get(Clinic.Status.ACTIVE, 0),
            "inactive": status_counts.get(Clinic.Status.SUSPENDED, 0)
            + status_counts.get(Clinic.Status.CANCELED, 0),
            "trial": status_counts.get(Clinic.Status.TRIAL, 0),
        }
        return context


class ClinicCreateForm(ClinicForm):
    """Cadastro de clinica com criacao opcional do administrador local."""

    admin_email = forms.EmailField(label="E-mail do administrador da clinica", required=False)
    admin_name = forms.CharField(label="Nome do administrador", max_length=180, required=False)
    plan = forms.ModelChoiceField(label="Plano", queryset=Plan.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Plan.objects.filter(is_active=True)


class ClinicCreateView(UnscopedMixin, CreateView):
    model = Clinic
    form_class = ClinicCreateForm
    template_name = "platform/clinic_form.html"
    unscoped_reason = "cadastro de clinica"

    def form_valid(self, form):
        clinic = form.save()
        _clinic, provisional = services.provision_clinic(
            clinic,
            admin_email=form.cleaned_data.get("admin_email", ""),
            admin_name=form.cleaned_data.get("admin_name", ""),
            plan=form.cleaned_data.get("plan"),
        )
        self.object = clinic
        log_action(
            AuditAction.CREATE,
            obj=clinic,
            description="Clinica cadastrada pelo painel da plataforma",
            request=self.request,
            clinic=clinic,
        )
        if provisional:
            messages.success(
                self.request,
                f"Clinica criada. Senha provisoria do administrador: {provisional}",
            )
        else:
            messages.success(self.request, "Clinica criada com sucesso.")
        return redirect("platform:clinic-detail", pk=clinic.pk)


class ClinicUpdateView(UnscopedMixin, UpdateView):
    model = Clinic
    form_class = ClinicForm
    template_name = "platform/clinic_form.html"
    unscoped_reason = "edicao de clinica"

    def get_success_url(self):
        return reverse_lazy("platform:clinic-detail", args=[self.object.pk])

    def form_valid(self, form):
        messages.success(self.request, "Clinica atualizada.")
        return super().form_valid(form)


class ClinicDetailView(UnscopedMixin, DetailView):
    model = Clinic
    template_name = "platform/clinic_detail.html"
    context_object_name = "clinic"
    unscoped_reason = "consulta administrativa de clinica"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clinic = self.object
        log_action(
            AuditAction.PLATFORM_ACCESS,
            obj=clinic,
            description="SUPERADMIN consultou os dados administrativos da clinica",
            request=self.request,
            clinic=clinic,
            is_sensitive=True,
        )
        with tenant_context(clinic):
            from apps.patients.models import Patient
            from apps.professionals.models import Professional
            from apps.scheduling.models import Appointment

            context.update(
                {
                    "patients_count": Patient.objects.count(),
                    "professionals_count": Professional.objects.filter(is_active=True).count(),
                    "appointments_count": Appointment.objects.count(),
                }
            )
        context["memberships"] = (
            ClinicMembership.all_objects.filter(clinic=clinic, is_deleted=False)
            .select_related("user")
            .order_by("role", "user__full_name")
        )
        context["subscription"] = getattr(clinic, "subscription", None)
        context["audit"] = AuditLog.objects.filter(clinic=clinic).select_related("user")[:15]
        context["modules"] = clinic.enabled_modules()
        return context


class ClinicStatusView(UnscopedMixin, View):
    unscoped_reason = "alteracao de status de clinica"

    def post(self, request, pk, status):
        clinic = get_object_or_404(Clinic.objects.all(), pk=pk)
        if status not in Clinic.Status.values:
            messages.error(request, "Status invalido.")
            return redirect("platform:clinic-detail", pk=pk)
        clinic.status = status
        clinic.save(update_fields=["status", "updated_at"])
        log_action(
            AuditAction.SETTINGS_CHANGE,
            obj=clinic,
            description=f"Status da clinica alterado para {clinic.get_status_display()}",
            request=request,
            clinic=clinic,
        )
        messages.success(request, f"Clinica marcada como {clinic.get_status_display()}.")
        return redirect("platform:clinic-detail", pk=pk)


class ClinicImpersonateView(UnscopedMixin, View):
    """
    Ativa uma clinica para suporte tecnico.

    O acesso e permitido pelo perfil SUPERADMIN, porem sempre registrado com
    identificacao do responsavel, data/hora e IP.
    """

    unscoped_reason = "acesso de suporte a clinica"

    def post(self, request, pk):
        clinic = get_object_or_404(Clinic.objects.all(), pk=pk)
        request.session[SESSION_CLINIC_KEY] = str(clinic.pk)
        log_action(
            AuditAction.PLATFORM_ACCESS,
            obj=clinic,
            description="SUPERADMIN entrou no painel operacional da clinica (suporte)",
            request=request,
            clinic=clinic,
            is_sensitive=True,
        )
        messages.warning(
            request,
            f"Voce esta operando dentro de {clinic}. Este acesso foi registrado na auditoria.",
        )
        return redirect("dashboard:clinic")


class PlatformUserListView(UnscopedMixin, ListView):
    """
    Lista global de usuarios, organizada por vinculo com clinica (um
    usuario com acesso a 2 clinicas aparece uma vez em cada uma -- a
    listagem e sobre `ClinicMembership`, nao sobre `User`, exatamente por
    isso). Quando uma clinica e selecionada no filtro, mostra so os
    vinculos dela; sem filtro, agrupa por clinica no template.
    """

    model = ClinicMembership
    template_name = "platform/user_list.html"
    context_object_name = "memberships"
    paginate_by = 50
    unscoped_reason = "listagem global de usuarios"

    def get_queryset(self):
        queryset = ClinicMembership.objects.select_related("user", "clinic")
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(user__full_name__icontains=search) | Q(user__email__icontains=search)
            )
        role = self.request.GET.get("role", "")
        if role:
            queryset = queryset.filter(role=role)
        clinic = self.request.GET.get("clinic", "")
        if clinic:
            queryset = queryset.filter(clinic_id=clinic)
        status = self.request.GET.get("status", "")
        if status == "active":
            queryset = queryset.filter(is_active=True, user__is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(Q(is_active=False) | Q(user__is_active=False))
        return queryset.order_by("clinic__trade_name", "user__full_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["role_choices"] = Roles.CHOICES
        context["clinic_choices"] = Clinic.objects.order_by("trade_name")

        base_users = User.objects.filter(role__in=[r for r, _ in Roles.CHOICES])
        by_role = dict(base_users.values_list("role").annotate(total=Count("id")))
        context["summary"] = {
            "total": base_users.count(),
            "active": base_users.filter(is_active=True).count(),
            "inactive": base_users.filter(is_active=False).count(),
            "admins": by_role.get(Roles.CLINIC_ADMIN, 0),
            "receptionists": by_role.get(Roles.RECEPTIONIST, 0),
            "professionals": by_role.get(Roles.PROFESSIONAL, 0),
        }
        return context


class PlatformUserToggleView(UnscopedMixin, View):
    unscoped_reason = "bloqueio/desbloqueio de usuario"

    def post(self, request, pk):
        user = get_object_or_404(User.objects.all(), pk=pk)
        if user.pk == request.user.pk:
            messages.error(request, "Voce nao pode desativar a propria conta.")
            return redirect("platform:user-list")
        user.is_active = not user.is_active
        user.locked_until = None
        user.save(update_fields=["is_active", "locked_until"])
        log_action(
            AuditAction.PERMISSION_CHANGE,
            obj=user,
            description=("Usuario reativado" if user.is_active else "Usuario desativado"),
            request=request,
        )
        messages.success(request, "Status do usuario atualizado.")
        return redirect("platform:user-list")


class PlatformUserPasswordResetView(UnscopedMixin, View):
    """Definir/redefinir a senha de qualquer usuario da plataforma."""

    unscoped_reason = "redefinicao de senha de usuario"
    template_name = "platform/user_password_form.html"

    def get(self, request, pk):
        target_user = get_object_or_404(User.objects.all(), pk=pk)
        if target_user.pk == request.user.pk:
            messages.error(
                request, "Para alterar a propria senha, use 'Trocar senha' em Seguranca."
            )
            return redirect("platform:user-list")
        return render(request, self.template_name, {
            "form": AdminSetPasswordForm(), "target_user": target_user,
        })

    def post(self, request, pk):
        from apps.accounts.services import admin_set_password

        target_user = get_object_or_404(User.objects.all(), pk=pk)
        if target_user.pk == request.user.pk:
            messages.error(
                request, "Para alterar a propria senha, use 'Trocar senha' em Seguranca."
            )
            return redirect("platform:user-list")

        form = AdminSetPasswordForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {
                "form": form, "target_user": target_user,
            })

        raw_password = (
            form.cleaned_data["password1"]
            if form.cleaned_data["mode"] == AdminSetPasswordForm.MODE_MANUAL
            else None
        )
        password = admin_set_password(
            target_user, raw_password=raw_password,
            force_change=form.cleaned_data["force_change"],
        )
        log_action(
            AuditAction.PASSWORD_CHANGE, obj=target_user,
            description=f"Senha redefinida pelo superadmin {request.user.email}",
            request=request, is_sensitive=True,
        )
        if raw_password is None:
            messages.success(
                request,
                f"Nova senha provisoria gerada para {target_user.email}: {password} "
                "(anote agora -- ela nao sera exibida novamente).",
            )
        else:
            messages.success(request, f"Senha de {target_user.email} definida com sucesso.")
        return redirect("platform:user-list")


class PlatformAuditView(UnscopedMixin, ListView):
    model = AuditLog
    template_name = "platform/audit_list.html"
    context_object_name = "logs"
    paginate_by = 60
    unscoped_reason = "auditoria global"

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user", "clinic")
        clinic = self.request.GET.get("clinic", "")
        if clinic:
            queryset = queryset.filter(clinic_id=clinic)
        action = self.request.GET.get("action", "")
        if action:
            queryset = queryset.filter(action=action)
        if self.request.GET.get("sensitive") == "1":
            queryset = queryset.filter(is_sensitive=True)
        if self.request.GET.get("denied") == "1":
            queryset = queryset.filter(result="denied")
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(user_email__icontains=search)
                | Q(object_repr__icontains=search)
                | Q(description__icontains=search)
            )
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["clinics"] = Clinic.objects.order_by("trade_name")
        context["actions"] = AuditAction.choices
        return context


class SecurityOverviewView(UnscopedMixin, TemplateView):
    template_name = "platform/security.html"
    unscoped_reason = "monitoramento de seguranca"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["failed_attempts"] = LoginAttempt.objects.filter(successful=False)[:50]
        context["locked_users"] = User.objects.filter(locked_until__isnull=False).order_by(
            "-locked_until"
        )[:20]
        context["denied"] = AuditLog.objects.filter(result="denied").select_related(
            "user", "clinic"
        )[:30]
        context["sensitive_access"] = AuditLog.objects.filter(
            is_sensitive=True, action=AuditAction.VIEW_SENSITIVE
        ).select_related("user", "clinic")[:30]
        return context


class PlanForm(BootstrapFormMixin, forms.ModelForm):
    from apps.clinics.modules import MODULE_CATALOG as _CATALOG

    modules = forms.MultipleChoiceField(
        label="Modulos incluidos",
        required=False,
        choices=[(code, label) for code, (label, _d) in _CATALOG.items()],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Plan
        fields = [
            "name",
            "tier",
            "description",
            "monthly_price",
            "yearly_price",
            "max_professionals",
            "max_users",
            "max_patients",
            "max_storage_mb",
            "max_clinics",
            "supports_api",
            "priority_support",
            "trial_days",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_saved:
            self.fields["modules"].initial = self.instance.modules or []

    def save(self, commit=True):
        plan = super().save(commit=False)
        plan.modules = list(self.cleaned_data.get("modules") or [])
        if commit:
            plan.save()
        return plan


class PlanListView(UnscopedMixin, ListView):
    model = Plan
    template_name = "platform/plan_list.html"
    context_object_name = "plans"
    unscoped_reason = "gestao de planos"

    def get_queryset(self):
        return Plan.objects.annotate(subscribers=Count("subscriptions")).order_by("monthly_price")


class PlanDetailView(UnscopedMixin, DetailView):
    model = Plan
    template_name = "platform/plan_detail.html"
    context_object_name = "plan"
    unscoped_reason = "consulta administrativa de plano"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["subscriptions"] = self.object.subscriptions.select_related("clinic").order_by(
            "clinic__trade_name"
        )
        return context


class PlanCreateView(UnscopedMixin, CreateView):
    model = Plan
    form_class = PlanForm
    template_name = "platform/plan_form.html"
    success_url = reverse_lazy("platform:plan-list")
    unscoped_reason = "criacao de plano"


class PlanUpdateView(UnscopedMixin, UpdateView):
    model = Plan
    form_class = PlanForm
    template_name = "platform/plan_form.html"
    success_url = reverse_lazy("platform:plan-list")
    unscoped_reason = "edicao de plano"


class SubscriptionListView(UnscopedMixin, ListView):
    model = Subscription
    template_name = "platform/subscription_list.html"
    context_object_name = "subscriptions"
    paginate_by = 30
    unscoped_reason = "gestao de assinaturas"

    def get_queryset(self):
        return Subscription.objects.select_related("clinic", "plan").order_by("clinic__trade_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoices"] = Invoice.objects.select_related("subscription__clinic")[:20]
        return context


class OrganizationListView(UnscopedMixin, ListView):
    model = Organization
    template_name = "platform/organization_list.html"
    context_object_name = "organizations"
    unscoped_reason = "gestao de organizacoes"

    def get_queryset(self):
        return Organization.objects.annotate(total_clinics=Count("clinics")).order_by("name")


class OrganizationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "trade_name", "document", "contact_email", "contact_phone", "is_active"]


class OrganizationCreateView(UnscopedMixin, CreateView):
    model = Organization
    form_class = OrganizationForm
    template_name = "platform/organization_form.html"
    unscoped_reason = "cadastro de organizacao"

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            AuditAction.CREATE,
            obj=self.object,
            description="Organizacao cadastrada pelo painel da plataforma",
            request=self.request,
        )
        messages.success(self.request, "Organizacao criada.")
        return response

    def get_success_url(self):
        return reverse_lazy("platform:organization-detail", args=[self.object.pk])


class OrganizationUpdateView(UnscopedMixin, UpdateView):
    model = Organization
    form_class = OrganizationForm
    template_name = "platform/organization_form.html"
    unscoped_reason = "edicao de organizacao"

    def form_valid(self, form):
        messages.success(self.request, "Organizacao atualizada.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("platform:organization-detail", args=[self.object.pk])


class OrganizationDetailView(UnscopedMixin, DetailView):
    model = Organization
    template_name = "platform/organization_detail.html"
    context_object_name = "organization"
    unscoped_reason = "consulta administrativa de organizacao"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clinics = self.object.clinics.select_related("subscription__plan").order_by("trade_name")
        context["clinics"] = clinics
        context["total_users"] = ClinicMembership.objects.filter(
            clinic__organization=self.object
        ).count()
        from apps.patients.models import Patient

        context["total_patients"] = Patient.objects.filter(
            clinic__organization=self.object
        ).count()
        context["available_clinics"] = Clinic.objects.filter(
            organization__isnull=True
        ).order_by("trade_name")
        return context


class OrganizationAddClinicView(UnscopedMixin, View):
    unscoped_reason = "associar clinica a organizacao"

    def post(self, request, pk):
        organization = get_object_or_404(Organization, pk=pk)
        clinic = get_object_or_404(Clinic, pk=request.POST.get("clinic"))
        clinic.organization = organization
        clinic.save(update_fields=["organization", "updated_at"])
        log_action(
            AuditAction.UPDATE,
            obj=clinic,
            description=f"Clinica associada a organizacao '{organization}'",
            request=request,
            clinic=clinic,
        )
        messages.success(request, f"{clinic} associada a {organization}.")
        return redirect("platform:organization-detail", pk=pk)


class OrganizationRemoveClinicView(UnscopedMixin, View):
    unscoped_reason = "remover clinica de organizacao"

    def post(self, request, pk, clinic_pk):
        organization = get_object_or_404(Organization, pk=pk)
        clinic = get_object_or_404(Clinic, pk=clinic_pk, organization=organization)
        clinic.organization = None
        clinic.save(update_fields=["organization", "updated_at"])
        log_action(
            AuditAction.UPDATE,
            obj=clinic,
            description=f"Clinica removida da organizacao '{organization}'",
            request=request,
            clinic=clinic,
        )
        messages.success(request, f"{clinic} removida de {organization}.")
        return redirect("platform:organization-detail", pk=pk)


# ---------------------------------------------------------------------------
# Financeiro do sistema (exclusivo do SUPERADMIN)
# ---------------------------------------------------------------------------
class FinanceDashboardView(UnscopedMixin, TemplateView):
    """Contabilidade da propria plataforma JJA System (nao das clinicas)."""

    template_name = "platform/finance_dashboard.html"
    unscoped_reason = "financeiro do sistema"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.billing.services import system_financial_metrics

        period = self.request.GET.get("period", "30d")
        start, end = period_range(
            period, self.request.GET.get("start", ""), self.request.GET.get("end", "")
        )
        context["metrics"] = system_financial_metrics(start, end)
        context["period"] = period
        context["start"] = start
        context["end"] = end
        return context


class SystemExpenseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SystemExpense
        fields = ["category", "description", "amount", "expense_date", "is_recurring", "notes"]
        widgets = {
            "expense_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class SystemExpenseListView(UnscopedMixin, ListView):
    model = SystemExpense
    template_name = "platform/system_expense_list.html"
    context_object_name = "expenses"
    paginate_by = 30
    unscoped_reason = "despesas do sistema"

    def get_queryset(self):
        return SystemExpense.objects.all().order_by("-expense_date")


class SystemExpenseCreateView(UnscopedMixin, CreateView):
    model = SystemExpense
    form_class = SystemExpenseForm
    template_name = "platform/system_expense_form.html"
    success_url = reverse_lazy("platform:system-expense-list")
    unscoped_reason = "lancamento de despesa do sistema"

    def form_valid(self, form):
        messages.success(self.request, "Despesa registrada.")
        return super().form_valid(form)


class SystemExpenseUpdateView(UnscopedMixin, UpdateView):
    model = SystemExpense
    form_class = SystemExpenseForm
    template_name = "platform/system_expense_form.html"
    success_url = reverse_lazy("platform:system-expense-list")
    unscoped_reason = "edicao de despesa do sistema"

    def form_valid(self, form):
        messages.success(self.request, "Despesa atualizada.")
        return super().form_valid(form)
