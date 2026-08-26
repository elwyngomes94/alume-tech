"""Views do financeiro da clinica."""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.core.mixins import ClinicViewMixin
from apps.core.utils import parse_date, period_range
from apps.finance import services
from apps.finance.forms import (
    CancelForm,
    CommissionRuleForm,
    CostCenterForm,
    FinancialCategoryForm,
    ManualTransactionForm,
    PayableForm,
    PaymentMethodForm,
    ReceivableForm,
    RegisterPaymentForm,
)
from apps.finance.models import (
    CostCenter,
    FinancialCategory,
    FinancialStatus,
    FinancialTransaction,
    PaymentMethod,
    PayableAccount,
    ProfessionalCommissionRule,
    ReceivableAccount,
)


class FinanceDashboardView(ClinicViewMixin, TemplateView):
    template_name = "finance/dashboard.html"
    required_permission = "finance.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.request.GET.get("period", "30d")
        start, end = period_range(
            period, self.request.GET.get("start", ""), self.request.GET.get("end", "")
        )
        services.refresh_overdue_statuses(self.request.clinic)
        context["summary"] = services.dashboard_summary(self.request.clinic, start, end)
        context["period"] = period
        context["start"] = start
        context["end"] = end
        return context


class ReceivableListView(ClinicViewMixin, ListView):
    model = ReceivableAccount
    template_name = "finance/receivable_list.html"
    context_object_name = "receivables"
    paginate_by = 25
    required_permission = "finance.view"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("patient", "professional", "category")
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get("q", "").strip()
        if search:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(patient__full_name__icontains=search) | Q(description__icontains=search)
            )
        return queryset.order_by("due_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = FinancialStatus.choices
        return context


class ReceivableCreateView(ClinicViewMixin, CreateView):
    model = ReceivableAccount
    form_class = ReceivableForm
    template_name = "finance/receivable_form.html"
    required_permission = "finance.add"
    success_url = reverse_lazy("finance:receivable-list")

    def form_valid(self, form):
        messages.success(self.request, "Conta a receber criada.")
        response = super().form_valid(form)
        return redirect("finance:receivable-detail", pk=self.object.pk)


class ReceivableUpdateView(ClinicViewMixin, UpdateView):
    model = ReceivableAccount
    form_class = ReceivableForm
    template_name = "finance/receivable_form.html"
    required_permission = "finance.change"

    def get_success_url(self):
        return reverse_lazy("finance:receivable-detail", args=[self.object.pk])

    def form_valid(self, form):
        messages.success(self.request, "Conta a receber atualizada.")
        return super().form_valid(form)


class ReceivableDetailView(ClinicViewMixin, DetailView):
    model = ReceivableAccount
    template_name = "finance/receivable_detail.html"
    context_object_name = "receivable"
    required_permission = "finance.view"

    def get_queryset(self):
        return super().get_queryset().select_related("patient", "professional", "service", "category")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pay_form"] = RegisterPaymentForm(initial={"paid_at": timezone.localdate()})
        context["cancel_form"] = CancelForm()
        context["payments"] = self.object.transactions.select_related("method").order_by("-paid_at")
        return context


class ReceivablePayView(ClinicViewMixin, View):
    required_permission = "finance.add"

    def post(self, request, pk):
        receivable = get_object_or_404(ReceivableAccount.objects.all(), pk=pk)
        form = RegisterPaymentForm(request.POST)
        if form.is_valid():
            try:
                services.register_receivable_payment(
                    receivable,
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    user=request.user,
                    paid_at=form.cleaned_data.get("paid_at"),
                    notes=form.cleaned_data.get("notes", ""),
                )
                messages.success(request, "Pagamento registrado com sucesso.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "Verifique os dados do pagamento.")
        return redirect("finance:receivable-detail", pk=pk)


class ReceivableCancelView(ClinicViewMixin, View):
    required_permission = "finance.cancel"

    def post(self, request, pk):
        receivable = get_object_or_404(ReceivableAccount.objects.all(), pk=pk)
        services.cancel_receivable(receivable, reason=request.POST.get("reason", ""))
        messages.success(request, "Conta a receber cancelada.")
        return redirect("finance:receivable-detail", pk=pk)


class PendingPaymentsView(ClinicViewMixin, ListView):
    """
    Fila de pagamentos em aberto pensada para a recepcao "dar baixa": mostra
    so o essencial (paciente, agendamento, profissional, procedimento, saldo)
    -- ao contrario de :class:`ReceivableListView`, que exige ``finance.view``
    e expõe todo o financeiro (comissoes, categorias etc).
    """

    model = ReceivableAccount
    template_name = "finance/pending_payments.html"
    context_object_name = "receivables"
    paginate_by = 30
    required_permission = "appointment.payment"

    def get_queryset(self):
        queryset = (
            super().get_queryset()
            .filter(
                status__in=[
                    FinancialStatus.PENDING, FinancialStatus.PARTIAL, FinancialStatus.OVERDUE,
                ]
            )
            .select_related("patient", "professional", "service", "appointment")
        )
        start = parse_date(self.request.GET.get("start", ""))
        end = parse_date(self.request.GET.get("end", ""))
        if start:
            queryset = queryset.filter(service_date__gte=start)
        if end:
            queryset = queryset.filter(service_date__lte=end)
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(patient__full_name__icontains=search)
        return queryset.order_by("service_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pay_form"] = RegisterPaymentForm(initial={"paid_at": timezone.localdate()})
        return context


class AppointmentReceivablePayView(ClinicViewMixin, View):
    """
    Dar baixa em um pagamento a partir da recepcao ou da tela do agendamento
    -- mesma regra de negocio de :class:`ReceivablePayView`, mas liberada
    para quem tem ``appointment.payment`` (recepcao), sem exigir acesso ao
    financeiro completo (``finance.add``).
    """

    required_permission = "appointment.payment"

    def post(self, request, pk):
        receivable = get_object_or_404(ReceivableAccount.objects.all(), pk=pk)
        form = RegisterPaymentForm(request.POST)
        if form.is_valid():
            try:
                services.register_receivable_payment(
                    receivable,
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    user=request.user,
                    paid_at=form.cleaned_data.get("paid_at"),
                    notes=form.cleaned_data.get("notes", ""),
                )
                messages.success(request, "Pagamento registrado com sucesso.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "Verifique os dados do pagamento.")
        return redirect(request.POST.get("next") or "finance:pending-payments")


class PayableListView(ClinicViewMixin, ListView):
    model = PayableAccount
    template_name = "finance/payable_list.html"
    context_object_name = "payables"
    paginate_by = 25
    required_permission = "finance.view"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("category", "cost_center")
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(supplier_name__icontains=search)
        return queryset.order_by("due_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = FinancialStatus.choices
        return context


class PayableCreateView(ClinicViewMixin, CreateView):
    model = PayableAccount
    form_class = PayableForm
    template_name = "finance/payable_form.html"
    required_permission = "finance.add"

    def form_valid(self, form):
        payable = form.save(commit=False)
        upload = form.cleaned_data.get("receipt_file")
        if upload:
            payable.attachment = services.create_receipt_document(
                self.request.clinic, self.request.user, upload
            )
        payable.save()
        self.object = payable
        messages.success(self.request, "Conta a pagar criada.")
        return redirect("finance:payable-detail", pk=payable.pk)


class PayableUpdateView(ClinicViewMixin, UpdateView):
    model = PayableAccount
    form_class = PayableForm
    template_name = "finance/payable_form.html"
    required_permission = "finance.change"

    def get_success_url(self):
        return reverse_lazy("finance:payable-detail", args=[self.object.pk])

    def form_valid(self, form):
        payable = form.save(commit=False)
        upload = form.cleaned_data.get("receipt_file")
        if upload:
            payable.attachment = services.create_receipt_document(
                self.request.clinic, self.request.user, upload
            )
        payable.save()
        self.object = payable
        messages.success(self.request, "Conta a pagar atualizada.")
        return redirect(self.get_success_url())


class PayableDetailView(ClinicViewMixin, DetailView):
    model = PayableAccount
    template_name = "finance/payable_detail.html"
    context_object_name = "payable"
    required_permission = "finance.view"

    def get_queryset(self):
        return super().get_queryset().select_related("category", "cost_center", "attachment")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pay_form"] = RegisterPaymentForm(initial={"paid_at": timezone.localdate()})
        context["cancel_form"] = CancelForm()
        context["payments"] = self.object.transactions.select_related("method").order_by("-paid_at")
        return context


class PayablePayView(ClinicViewMixin, View):
    required_permission = "finance.add"

    def post(self, request, pk):
        payable = get_object_or_404(PayableAccount.objects.all(), pk=pk)
        form = RegisterPaymentForm(request.POST)
        if form.is_valid():
            try:
                services.register_payable_payment(
                    payable,
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    user=request.user,
                    paid_at=form.cleaned_data.get("paid_at"),
                    notes=form.cleaned_data.get("notes", ""),
                )
                messages.success(request, "Pagamento registrado com sucesso.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "Verifique os dados do pagamento.")
        return redirect("finance:payable-detail", pk=pk)


class PayableCancelView(ClinicViewMixin, View):
    required_permission = "finance.cancel"

    def post(self, request, pk):
        payable = get_object_or_404(PayableAccount.objects.all(), pk=pk)
        services.cancel_payable(payable, reason=request.POST.get("reason", ""))
        messages.success(request, "Conta a pagar cancelada.")
        return redirect("finance:payable-detail", pk=pk)


class CashFlowView(ClinicViewMixin, TemplateView):
    template_name = "finance/cashflow.html"
    required_permission = "finance.cashflow.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.request.GET.get("period", "30d")
        start, end = period_range(
            period, self.request.GET.get("start", ""), self.request.GET.get("end", "")
        )
        filters = {
            "category": self.request.GET.get("category", ""),
            "method": self.request.GET.get("method", ""),
            "cost_center": self.request.GET.get("cost_center", ""),
            "professional": self.request.GET.get("professional", ""),
            "kind": self.request.GET.get("kind", ""),
        }
        context["entries"] = services.cashflow_entries(
            self.request.clinic, start, end, **{k: v for k, v in filters.items() if v}
        )
        context["opening_balance"] = services.opening_balance(self.request.clinic, start)
        context["period"] = period
        context["start"] = start
        context["end"] = end
        context["categories"] = FinancialCategory.objects.filter(is_active=True)
        context["methods"] = PaymentMethod.objects.filter(is_active=True)
        context["cost_centers"] = CostCenter.objects.filter(is_active=True)
        from apps.professionals.models import Professional

        context["professionals"] = Professional.objects.filter(is_active=True)
        return context


class ManualTransactionCreateView(ClinicViewMixin, View):
    required_permission = "finance.add"

    def get(self, request):
        from django.shortcuts import render

        return render(request, "finance/transaction_form.html", {
            "form": ManualTransactionForm(initial={"paid_at": timezone.localdate()})
        })

    def post(self, request):
        from django.shortcuts import render

        form = ManualTransactionForm(request.POST)
        if form.is_valid():
            services.create_manual_transaction(
                clinic=request.clinic,
                kind=form.cleaned_data["kind"],
                amount=form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                category=form.cleaned_data.get("category"),
                cost_center=form.cleaned_data.get("cost_center"),
                user=request.user,
                paid_at=form.cleaned_data.get("paid_at"),
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(request, "Lancamento registrado.")
            return redirect("finance:cashflow")
        messages.error(request, "Verifique os campos do lancamento.")
        return render(request, "finance/transaction_form.html", {"form": form})


# ---------------------------------------------------------------------------
# Configuracoes (categorias, centros de custo, formas de pagamento)
# ---------------------------------------------------------------------------
class FinanceSettingsView(ClinicViewMixin, TemplateView):
    template_name = "finance/settings.html"
    required_permission = "finance.category.manage"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["income_categories"] = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.INCOME
        )
        context["expense_categories"] = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.EXPENSE
        )
        context["cost_centers"] = CostCenter.objects.all()
        context["payment_methods"] = PaymentMethod.objects.all()
        return context


class _FinanceCatalogCreateView(ClinicViewMixin, CreateView):
    template_name = "finance/catalog_form.html"
    success_url = reverse_lazy("finance:settings")
    required_permission = "finance.category.manage"
    entity_label = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity_label"] = self.entity_label
        return context

    def form_valid(self, form):
        messages.success(self.request, f"{self.entity_label} salvo(a).")
        return super().form_valid(form)


class _FinanceCatalogUpdateView(ClinicViewMixin, UpdateView):
    template_name = "finance/catalog_form.html"
    success_url = reverse_lazy("finance:settings")
    required_permission = "finance.category.manage"
    entity_label = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity_label"] = self.entity_label
        return context

    def form_valid(self, form):
        messages.success(self.request, f"{self.entity_label} atualizado(a).")
        return super().form_valid(form)


class FinancialCategoryCreateView(_FinanceCatalogCreateView):
    model = FinancialCategory
    form_class = FinancialCategoryForm
    entity_label = "Categoria"

    def get_initial(self):
        initial = super().get_initial()
        kind = self.request.GET.get("kind", "")
        if kind in FinancialCategory.Kind.values:
            initial["kind"] = kind
        return initial


class FinancialCategoryUpdateView(_FinanceCatalogUpdateView):
    model = FinancialCategory
    form_class = FinancialCategoryForm
    entity_label = "Categoria"


class CostCenterCreateView(_FinanceCatalogCreateView):
    model = CostCenter
    form_class = CostCenterForm
    entity_label = "Centro de custo"


class CostCenterUpdateView(_FinanceCatalogUpdateView):
    model = CostCenter
    form_class = CostCenterForm
    entity_label = "Centro de custo"


class PaymentMethodCreateView(_FinanceCatalogCreateView):
    model = PaymentMethod
    form_class = PaymentMethodForm
    entity_label = "Forma de pagamento"


class PaymentMethodUpdateView(_FinanceCatalogUpdateView):
    model = PaymentMethod
    form_class = PaymentMethodForm
    entity_label = "Forma de pagamento"


class CommissionRuleListView(ClinicViewMixin, ListView):
    model = ProfessionalCommissionRule
    template_name = "finance/commission_list.html"
    context_object_name = "rules"
    required_permission = "finance.commission.view"

    def get_queryset(self):
        return super().get_queryset().select_related("professional", "service")


class CommissionRuleCreateView(ClinicViewMixin, CreateView):
    model = ProfessionalCommissionRule
    form_class = CommissionRuleForm
    template_name = "finance/commission_form.html"
    required_permission = "finance.category.manage"
    success_url = reverse_lazy("finance:commission-list")

    def form_valid(self, form):
        messages.success(self.request, "Regra de comissao criada.")
        return super().form_valid(form)


class CommissionRuleUpdateView(ClinicViewMixin, UpdateView):
    model = ProfessionalCommissionRule
    form_class = CommissionRuleForm
    template_name = "finance/commission_form.html"
    required_permission = "finance.category.manage"
    success_url = reverse_lazy("finance:commission-list")

    def form_valid(self, form):
        messages.success(self.request, "Regra de comissao atualizada.")
        return super().form_valid(form)
