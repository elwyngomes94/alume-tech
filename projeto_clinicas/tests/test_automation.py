"""
Testes da Fase 1 do motor de automacao: engine (idempotencia/skip/falha),
lista de espera automatica, baixa via webhook financeiro e comprovante de
pagamento automatico.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.automation.models import AutomationExecution, AutomationSettings
from apps.automation.services import engine
from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.finance import services as finance_services
from apps.finance.models import FinancialStatus, FinancialTransaction, ReceivableAccount
from apps.scheduling import services as scheduling_services
from apps.scheduling.models import Appointment, WaitingListEntry
from tests.factories import (
    make_admin,
    make_appointment,
    make_clinic,
    make_financial_category,
    make_patient,
    make_payment_method,
    make_professional_user,
    make_receptionist,
    make_service,
)


class AutomationEngineTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()

    def test_idempotencia_nao_repete_a_acao(self):
        calls = []
        with tenant_context(self.clinic):
            for _ in range(2):
                engine.run(
                    "waiting_list_invite", self.clinic,
                    idempotency_key="chave-fixa",
                    action=lambda: calls.append(1) or {},
                )
        self.assertEqual(len(calls), 1)

    def test_condicao_falsa_marca_ignorada_e_nao_executa_acao(self):
        calls = []
        with tenant_context(self.clinic):
            execution = engine.run(
                "waiting_list_invite", self.clinic,
                idempotency_key="chave-condicao",
                action=lambda: calls.append(1),
                condition=lambda: False,
            )
        self.assertEqual(execution.status, AutomationExecution.Status.SKIPPED)
        self.assertEqual(calls, [])

    def test_excecao_na_acao_marca_falhou_e_nao_propaga(self):
        def boom():
            raise RuntimeError("falha proposital")

        with tenant_context(self.clinic):
            execution = engine.run(
                "waiting_list_invite", self.clinic, idempotency_key="chave-erro", action=boom,
            )
        self.assertEqual(execution.status, AutomationExecution.Status.FAILED)
        self.assertIn("falha proposital", execution.last_error)
        self.assertEqual(execution.attempts, 1)

    def test_isolamento_entre_clinicas(self):
        other_clinic = make_clinic()
        with tenant_context(self.clinic):
            engine.run(
                "waiting_list_invite", self.clinic, idempotency_key="isolamento",
                action=lambda: {},
            )
        with tenant_context(other_clinic):
            ids = set(AutomationExecution.objects.values_list("pk", flat=True))
        self.assertEqual(ids, set())


class WaitingListAutomationTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_admin(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient_booked = make_patient(self.clinic, full_name="Paciente agendado")
        self.patient_waiting = make_patient(self.clinic, full_name="Paciente esperando")
        self.appointment = make_appointment(
            self.clinic, self.patient_booked, self.professional,
        )
        with tenant_context(self.clinic):
            self.entry = WaitingListEntry.objects.create(
                patient=self.patient_waiting, professional=self.professional,
                status=WaitingListEntry.Status.WAITING,
            )

    def test_cancelamento_com_entrada_compativel_notifica_e_marca_contatada(self):
        with tenant_context(self.clinic):
            scheduling_services.change_status(self.appointment, Appointment.Status.CANCELED)
            self.entry.refresh_from_db()
            execution = AutomationExecution.objects.filter(
                automation__codename="waiting_list_invite"
            ).first()
        self.assertEqual(self.entry.status, WaitingListEntry.Status.CONTACTED)
        self.assertIsNotNone(self.entry.contacted_at)
        self.assertEqual(execution.status, AutomationExecution.Status.SUCCESS)

        from apps.notifications.models import Notification

        with tenant_context(self.clinic):
            self.assertTrue(
                Notification.objects.filter(
                    recipient=self.admin, title__icontains="lista de espera"
                ).exists()
            )

    def test_sem_entrada_compativel_nao_faz_nada(self):
        _other_user, other_professional = make_professional_user(self.clinic)
        with tenant_context(self.clinic):
            self.entry.professional = other_professional
            self.entry.save()
            scheduling_services.change_status(self.appointment, Appointment.Status.CANCELED)
            execution = AutomationExecution.objects.filter(
                automation__codename="waiting_list_invite"
            ).first()
            self.entry.refresh_from_db()
        self.assertEqual(execution.status, AutomationExecution.Status.SKIPPED)
        self.assertEqual(self.entry.status, WaitingListEntry.Status.WAITING)

    def test_desligado_nas_configuracoes_nao_dispara(self):
        AutomationSettings.objects.update_or_create(
            clinic=self.clinic, defaults={"waiting_list_auto_invite": False},
        )
        with tenant_context(self.clinic):
            scheduling_services.change_status(self.appointment, Appointment.Status.CANCELED)
            execution = AutomationExecution.objects.filter(
                automation__codename="waiting_list_invite"
            ).first()
            self.entry.refresh_from_db()
        self.assertEqual(execution.status, AutomationExecution.Status.SKIPPED)
        self.assertEqual(self.entry.status, WaitingListEntry.Status.WAITING)


class PaymentReceiptAutomationTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.method = make_payment_method(self.clinic)
        make_financial_category(self.clinic, "income")

    def _make_receivable(self):
        with tenant_context(self.clinic):
            from apps.finance.models import FinancialCategory

            category = FinancialCategory.objects.filter(kind="income").first()
            return ReceivableAccount.objects.create(
                clinic=self.clinic, patient=self.patient, category=category,
                due_date=timezone.localdate(), gross_amount=Decimal("100.00"),
            )

    def test_baixa_manual_gera_um_comprovante(self):
        receivable = self._make_receivable()
        with tenant_context(self.clinic):
            finance_services.register_receivable_payment(
                receivable, amount=Decimal("100.00"), method=self.method,
            )
            documents = Document.objects.filter(
                patient=self.patient, category__name="Comprovante de pagamento"
            )
        self.assertEqual(documents.count(), 1)

    def test_desligado_nas_configuracoes_nao_gera_comprovante(self):
        AutomationSettings.objects.update_or_create(
            clinic=self.clinic, defaults={"auto_generate_receipt": False},
        )
        receivable = self._make_receivable()
        with tenant_context(self.clinic):
            finance_services.register_receivable_payment(
                receivable, amount=Decimal("100.00"), method=self.method,
            )
            documents = Document.objects.filter(
                patient=self.patient, category__name="Comprovante de pagamento"
            )
        self.assertEqual(documents.count(), 0)


class FinancialWebhookTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.method = make_payment_method(self.clinic)
        make_financial_category(self.clinic, "income")
        with tenant_context(self.clinic):
            from apps.finance.models import FinancialCategory

            category = FinancialCategory.objects.filter(kind="income").first()
            self.receivable = ReceivableAccount.objects.create(
                clinic=self.clinic, patient=self.patient, category=category,
                due_date=timezone.localdate(), gross_amount=Decimal("150.00"),
            )
        self.settings_obj = AutomationSettings.objects.create(
            clinic=self.clinic, financial_webhook_enabled=True,
        )

    def _payload(self, **overrides):
        payload = {
            "receivable_id": str(self.receivable.pk),
            "amount": "150.00",
            "method_id": str(self.method.pk),
            "external_reference": "ref-123",
        }
        payload.update(overrides)
        return payload

    def _post(self, payload, secret=None):
        secret = secret if secret is not None else self.settings_obj.financial_webhook_secret
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        client = Client()
        return client.post(
            reverse("automation:financial-webhook", args=[self.clinic.pk]),
            data=body, content_type="application/json",
            HTTP_X_JJA_SIGNATURE=signature,
        )

    def test_assinatura_valida_registra_pagamento(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 200)
        with tenant_context(self.clinic):
            self.receivable.refresh_from_db()
        self.assertEqual(self.receivable.status, FinancialStatus.PAID)

    def test_reenvio_do_mesmo_webhook_e_idempotente(self):
        self._post(self._payload())
        self._post(self._payload())
        with tenant_context(self.clinic):
            count = FinancialTransaction.objects.filter(receivable=self.receivable).count()
        self.assertEqual(count, 1)

    def test_assinatura_invalida_e_rejeitada(self):
        response = self._post(self._payload(), secret="segredo-errado")
        self.assertEqual(response.status_code, 401)
        with tenant_context(self.clinic):
            self.receivable.refresh_from_db()
        self.assertEqual(self.receivable.status, FinancialStatus.PENDING)

    def test_webhook_desligado_por_padrao_retorna_404(self):
        other_clinic = make_clinic()
        client = Client()
        response = client.post(
            reverse("automation:financial-webhook", args=[other_clinic.pk]),
            data=b"{}", content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class AutomationPermissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_admin(self.clinic)
        self.receptionist = make_receptionist(self.clinic)

    def test_administrador_tem_permissoes_de_automacao_por_padrao(self):
        self.assertTrue(self.admin.has_clinic_perm("automation.view", self.clinic))
        self.assertTrue(self.admin.has_clinic_perm("automation.manage", self.clinic))

    def test_recepcionista_nao_tem_permissoes_de_automacao_por_padrao(self):
        self.assertFalse(self.receptionist.has_clinic_perm("automation.view", self.clinic))

    def test_administrador_acessa_configuracoes(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("automation:settings"))
        self.assertEqual(response.status_code, 200)

    def test_recepcionista_recebe_403_nas_configuracoes(self):
        client = Client()
        client.force_login(self.receptionist)
        response = client.get(reverse("automation:settings"))
        self.assertEqual(response.status_code, 403)

    def test_administrador_acessa_historico(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("automation:execution-list"))
        self.assertEqual(response.status_code, 200)
