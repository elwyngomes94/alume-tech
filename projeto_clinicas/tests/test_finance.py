"""Testes do modulo financeiro: isolamento, permissoes e regras de negocio."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.permissions import Roles
from apps.core.tenancy import tenant_context
from apps.finance import services
from apps.finance.models import FinancialStatus, ProfessionalCommissionRule
from tests.factories import (
    make_admin,
    make_clinic,
    make_financial_category,
    make_membership,
    make_patient,
    make_payable,
    make_payment_method,
    make_professional_user,
    make_receivable,
    make_user,
)


class FinanceIsolationTests(TestCase):
    """Clinica A nunca pode enxergar o financeiro da Clinica B (nos dois sentidos)."""

    def setUp(self):
        self.clinic_a = make_clinic()
        self.clinic_b = make_clinic()
        self.patient_a = make_patient(self.clinic_a)
        self.patient_b = make_patient(self.clinic_b)
        self.receivable_a = make_receivable(self.clinic_a, self.patient_a)
        self.receivable_b = make_receivable(self.clinic_b, self.patient_b)

    def test_tenant_a_nao_enxerga_conta_a_receber_da_clinica_b(self):
        from apps.finance.models import ReceivableAccount

        with tenant_context(self.clinic_a):
            ids = set(ReceivableAccount.objects.values_list("pk", flat=True))
        self.assertIn(self.receivable_a.pk, ids)
        self.assertNotIn(self.receivable_b.pk, ids)

    def test_tenant_b_nao_enxerga_conta_a_receber_da_clinica_a(self):
        from apps.finance.models import ReceivableAccount

        with tenant_context(self.clinic_b):
            ids = set(ReceivableAccount.objects.values_list("pk", flat=True))
        self.assertIn(self.receivable_b.pk, ids)
        self.assertNotIn(self.receivable_a.pk, ids)

    def test_usuario_da_clinica_a_nao_acessa_conta_da_clinica_b_via_http(self):
        admin_a = make_admin(self.clinic_a)
        client = Client()
        client.force_login(admin_a)
        response = client.get(reverse("finance:receivable-detail", args=[self.receivable_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_usuario_da_clinica_b_nao_acessa_conta_da_clinica_a_via_http(self):
        admin_b = make_admin(self.clinic_b)
        client = Client()
        client.force_login(admin_b)
        response = client.get(reverse("finance:receivable-detail", args=[self.receivable_a.pk]))
        self.assertEqual(response.status_code, 404)


class FinancePermissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()

    def test_usuario_sem_permissao_recebe_403_no_dashboard(self):
        user = make_user(role=Roles.RECEPTIONIST)
        make_membership(user, self.clinic, Roles.RECEPTIONIST)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("finance:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_administrador_da_clinica_acessa_dashboard_financeiro(self):
        admin = make_admin(self.clinic)
        client = Client()
        client.force_login(admin)
        response = client.get(reverse("finance:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_administrador_de_clinica_recebe_403_no_financeiro_do_sistema(self):
        admin = make_admin(self.clinic)
        client = Client()
        client.force_login(admin)
        response = client.get(reverse("platform:finance-dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_superadmin_acessa_financeiro_do_sistema(self):
        user = make_user(role=Roles.SUPERADMIN, is_superuser=True, is_staff=True)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("platform:finance-dashboard"))
        self.assertEqual(response.status_code, 200)


class ReceivablePaymentTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.method = make_payment_method(self.clinic)

    def test_pagamento_parcial_muda_status_para_parcial(self):
        receivable = make_receivable(self.clinic, self.patient, gross_amount=Decimal("200.00"))
        with tenant_context(self.clinic):
            services.register_receivable_payment(
                receivable, amount=Decimal("80.00"), method=self.method,
            )
            receivable.refresh_from_db()
            self.assertEqual(receivable.status, FinancialStatus.PARTIAL)
            self.assertEqual(receivable.balance, Decimal("120.00"))

    def test_pagamento_total_muda_status_para_pago(self):
        receivable = make_receivable(self.clinic, self.patient, gross_amount=Decimal("200.00"))
        with tenant_context(self.clinic):
            services.register_receivable_payment(
                receivable, amount=Decimal("200.00"), method=self.method,
            )
            receivable.refresh_from_db()
            self.assertEqual(receivable.status, FinancialStatus.PAID)
            self.assertEqual(receivable.balance, Decimal("0.00"))

    def test_nao_permite_pagar_mais_que_o_saldo(self):
        receivable = make_receivable(self.clinic, self.patient, gross_amount=Decimal("100.00"))
        with tenant_context(self.clinic):
            with self.assertRaises(ValidationError):
                services.register_receivable_payment(
                    receivable, amount=Decimal("150.00"), method=self.method,
                )

    def test_cancelar_conta_impede_novo_pagamento_via_status(self):
        receivable = make_receivable(self.clinic, self.patient)
        with tenant_context(self.clinic):
            services.cancel_receivable(receivable, reason="Erro de lancamento")
        receivable.refresh_from_db()
        self.assertEqual(receivable.status, FinancialStatus.CANCELED)


class PayablePaymentTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.method = make_payment_method(self.clinic)

    def test_pagamento_de_conta_a_pagar_atualiza_saldo(self):
        payable = make_payable(self.clinic, amount=Decimal("300.00"))
        with tenant_context(self.clinic):
            services.register_payable_payment(
                payable, amount=Decimal("300.00"), method=self.method,
            )
            payable.refresh_from_db()
            self.assertEqual(payable.status, FinancialStatus.PAID)
            self.assertEqual(payable.balance, Decimal("0.00"))


class CommissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.method = make_payment_method(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)

    def test_comissao_calculada_ao_quitar_conta(self):
        with tenant_context(self.clinic):
            ProfessionalCommissionRule.objects.create(
                professional=self.professional, percentage=Decimal("40"),
            )
            receivable = make_receivable(
                self.clinic, self.patient, professional=self.professional,
                gross_amount=Decimal("500.00"),
            )
            services.register_receivable_payment(
                receivable, amount=Decimal("500.00"), method=self.method,
            )
        receivable.refresh_from_db()
        self.assertEqual(receivable.professional_commission_amount, Decimal("200.00"))
        self.assertEqual(receivable.clinic_amount, Decimal("300.00"))

    def test_sem_regra_comissao_e_zero(self):
        with tenant_context(self.clinic):
            receivable = make_receivable(
                self.clinic, self.patient, professional=self.professional,
                gross_amount=Decimal("500.00"),
            )
            services.register_receivable_payment(
                receivable, amount=Decimal("500.00"), method=self.method,
            )
        receivable.refresh_from_db()
        self.assertEqual(receivable.professional_commission_amount, Decimal("0.00"))
        self.assertEqual(receivable.clinic_amount, Decimal("500.00"))

    def test_prioridade_regra_profissional_e_servico_sobre_regra_generica(self):
        from apps.clinics.models import Service

        with tenant_context(self.clinic):
            service = Service.objects.create(name="Consulta especial", price=Decimal("100"))
            ProfessionalCommissionRule.objects.create(
                professional=self.professional, service=None, percentage=Decimal("10"),
            )
            ProfessionalCommissionRule.objects.create(
                professional=self.professional, service=service, percentage=Decimal("50"),
            )
            rule = services.resolve_commission_rule(self.professional, service)
        self.assertEqual(rule.percentage, Decimal("50"))


class CashFlowTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.method = make_payment_method(self.clinic)

    def test_saldo_do_fluxo_de_caixa_soma_entradas_e_saidas(self):
        with tenant_context(self.clinic):
            receivable = make_receivable(self.clinic, self.patient, gross_amount=Decimal("300.00"))
            payable = make_payable(self.clinic, amount=Decimal("100.00"))
            services.register_receivable_payment(
                receivable, amount=Decimal("300.00"), method=self.method,
            )
            services.register_payable_payment(
                payable, amount=Decimal("100.00"), method=self.method,
            )
            from datetime import timedelta

            from django.utils import timezone

            start = timezone.localdate() - timedelta(days=1)
            end = timezone.localdate() + timedelta(days=1)
            entries = services.cashflow_entries(self.clinic, start, end)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1].running_balance, Decimal("200.00"))


class FinanceReportExportTests(TestCase):
    """Smoke test: relatorios financeiros exportam sem erro."""

    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        make_receivable(self.clinic, self.patient)
        self.admin = make_admin(self.clinic)

    def test_exportar_relatorio_contas_a_receber_em_csv(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(
            reverse("reports:export", args=["contas_receber", "csv"]) + "?period=30d"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))

    def test_relatorio_financeiro_exige_permissao_especifica(self):
        receptionist = make_user(role=Roles.RECEPTIONIST)
        make_membership(receptionist, self.clinic, Roles.RECEPTIONIST)
        client = Client()
        client.force_login(receptionist)
        response = client.get(reverse("reports:detail", args=["contas_receber"]))
        self.assertEqual(response.status_code, 403)
