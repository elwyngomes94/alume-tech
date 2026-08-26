"""Views das automacoes (Fase 1 -- Automacao Operacional)."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView, UpdateView

from apps.automation.forms import AutomationSettingsForm
from apps.automation.models import Automation, AutomationExecution
from apps.automation.services import engine
from apps.automation.services.financial_automation import (
    process_payment_webhook,
    verify_webhook_signature,
)
from apps.clinics.models import Clinic
from apps.core.mixins import ClinicViewMixin
from apps.core.tenancy import tenant_context
from apps.core.utils import parse_date


class AutomationSettingsView(ClinicViewMixin, UpdateView):
    form_class = AutomationSettingsForm
    template_name = "automation/settings.html"
    required_permission = "automation.manage"
    success_url = reverse_lazy("automation:settings")

    def get_object(self, queryset=None):
        return engine.get_settings(self.request.clinic)

    def form_valid(self, form):
        messages.success(self.request, "Configuracoes de automacao salvas.")
        return super().form_valid(form)


class RegenerateWebhookSecretView(ClinicViewMixin, View):
    required_permission = "automation.manage"

    def post(self, request):
        settings_obj = engine.get_settings(request.clinic)
        settings_obj.financial_webhook_secret = ""
        settings_obj.save()  # save() gera um novo segredo automaticamente quando vazio
        messages.success(request, "Novo segredo do webhook financeiro gerado.")
        return redirect("automation:settings")


class AutomationExecutionListView(ClinicViewMixin, ListView):
    model = AutomationExecution
    template_name = "automation/execution_list.html"
    context_object_name = "executions"
    paginate_by = 50
    required_permission = "automation.view"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("automation")
        automation = self.request.GET.get("automation", "")
        if automation:
            queryset = queryset.filter(automation__codename=automation)
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        start = parse_date(self.request.GET.get("start", ""))
        if start:
            queryset = queryset.filter(started_at__date__gte=start)
        end = parse_date(self.request.GET.get("end", ""))
        if end:
            queryset = queryset.filter(started_at__date__lte=end)
        return queryset.order_by("-started_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["automations"] = Automation.objects.all()
        context["status_choices"] = AutomationExecution.Status.choices
        return context


@method_decorator(csrf_exempt, name="dispatch")
class FinancialWebhookView(View):
    """
    Receptor generico de webhook financeiro (baixa automatica -- secao 1.3
    do pedido). Sem login: e uma integracao servidor-servidor, autenticada
    por assinatura HMAC-SHA256 no header ``X-JJA-Signature`` (calculada
    sobre o corpo bruto usando o segredo da clinica).

    Contrato do payload (JSON), generico e pronto para adaptar a qualquer
    provedor real no futuro::

        {"receivable_id": "<uuid>", "amount": "150.00",
         "method_id": "<uuid>", "external_reference": "opcional"}
    """

    def post(self, request, clinic_id):
        clinic = get_object_or_404(Clinic.objects.all(), pk=clinic_id)
        with tenant_context(clinic):
            settings_obj = engine.get_settings(clinic)
            if not settings_obj.financial_webhook_enabled:
                # Nao revela se a clinica existe ou apenas esta desabilitada.
                return HttpResponse(status=404)

            signature = request.headers.get("X-JJA-Signature", "")
            if not verify_webhook_signature(
                settings_obj.financial_webhook_secret, request.body, signature
            ):
                return JsonResponse({"detail": "assinatura invalida"}, status=401)

            try:
                payload = json.loads(request.body or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({"detail": "payload invalido"}, status=400)

            required = {"receivable_id", "amount", "method_id"}
            if not isinstance(payload, dict) or not required.issubset(payload):
                return JsonResponse({"detail": "campos obrigatorios ausentes"}, status=400)

            try:
                amount = Decimal(str(payload["amount"]))
            except InvalidOperation:
                return JsonResponse({"detail": "valor invalido"}, status=400)

            try:
                result = process_payment_webhook(
                    clinic,
                    receivable_id=payload["receivable_id"],
                    amount=amount,
                    method_id=payload["method_id"],
                    external_reference=payload.get("external_reference", ""),
                )
            except ObjectDoesNotExist:
                return JsonResponse(
                    {"detail": "conta a receber ou forma de pagamento nao encontrada"}, status=404
                )
            except DjangoValidationError as exc:
                return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
            return JsonResponse(result, status=200)
