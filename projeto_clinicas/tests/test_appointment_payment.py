"""
Testes da integracao agenda <-> financeiro: valor e forma de pagamento
definidos no momento do agendamento, "dar baixa" pela recepcao e
cancelamento com disposicao do valor ja recebido.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.finance.models import FinancialStatus, FinancialTransaction, ReceivableAccount
from apps.scheduling import services as scheduling_services
from apps.scheduling.forms import AppointmentForm
from apps.scheduling.models import Appointment
from tests.factories import (
    make_admin,
    make_clinic,
    make_financial_category,
    make_patient,
    make_payment_method,
    make_professional_user,
    make_receptionist,
    make_service,
)


class AppointmentBookingReceivableTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.service = make_service(self.clinic, price=Decimal("150.00"))
        self.method = make_payment_method(self.clinic)
        make_financial_category(self.clinic, "income")

    def _book(self, **kwargs):
        with tenant_context(self.clinic):
            return scheduling_services.create_appointment(
                clinic=self.clinic,
                patient=self.patient,
                professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1),
                service=self.service,
                **kwargs,
            )

    def test_agendamento_com_servico_gera_conta_a_receber_pendente(self):
        appointment = self._book()
        with tenant_context(self.clinic):
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.gross_amount, Decimal("150.00"))
            self.assertEqual(receivable.status, FinancialStatus.PENDING)
            self.assertEqual(receivable.paid_amount, Decimal("0.00"))

    def test_desconto_aplicado_no_agendamento(self):
        appointment = self._book(discount=Decimal("50.00"))
        with tenant_context(self.clinic):
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.net_amount, Decimal("100.00"))

    def test_pagar_na_hora_marca_como_pago_e_gera_transacao(self):
        appointment = self._book(payment_method=self.method, pay_now=True)
        with tenant_context(self.clinic):
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.status, FinancialStatus.PAID)
            self.assertEqual(receivable.paid_amount, Decimal("150.00"))
            self.assertTrue(
                FinancialTransaction.objects.filter(
                    receivable=receivable, kind=FinancialTransaction.Kind.INCOME
                ).exists()
            )

    def test_pagamento_parcial_na_hora_marca_conta_como_parcial(self):
        appointment = self._book(
            payment_method=self.method, pay_now=True, amount_paid_now=Decimal("50.00")
        )
        with tenant_context(self.clinic):
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.status, FinancialStatus.PARTIAL)
            self.assertEqual(receivable.balance, Decimal("100.00"))

    def test_cortesia_nao_gera_cobranca_nem_transacao(self):
        appointment = self._book(is_courtesy=True)
        with tenant_context(self.clinic):
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.status, FinancialStatus.COURTESY)
            self.assertEqual(receivable.paid_amount, Decimal("0.00"))
            self.assertFalse(FinancialTransaction.objects.filter(receivable=receivable).exists())

    def test_nao_duplica_conta_a_receber_ao_concluir_atendimento(self):
        appointment = self._book()
        with tenant_context(self.clinic):
            scheduling_services.change_status(appointment, Appointment.Status.CONFIRMED)
            scheduling_services.change_status(appointment, Appointment.Status.CHECKED_IN)
            scheduling_services.change_status(appointment, Appointment.Status.IN_PROGRESS)
            scheduling_services.change_status(appointment, Appointment.Status.COMPLETED)
            count = ReceivableAccount.objects.filter(appointment=appointment).count()
            self.assertEqual(count, 1)

    def test_constraint_impede_duas_contas_para_o_mesmo_agendamento(self):
        appointment = self._book()
        with tenant_context(self.clinic):
            from apps.finance.models import FinancialCategory

            category = FinancialCategory.objects.filter(
                kind=FinancialCategory.Kind.INCOME
            ).first()
            with self.assertRaises(IntegrityError):
                with db_transaction.atomic():
                    ReceivableAccount.objects.create(
                        clinic=self.clinic, patient=self.patient, appointment=appointment,
                        category=category, due_date=timezone.localdate(),
                        gross_amount=Decimal("1.00"),
                    )


class CancellationFinanceTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.service = make_service(self.clinic, price=Decimal("100.00"))
        self.method = make_payment_method(self.clinic)
        make_financial_category(self.clinic, "income")

    def _book(self, **kwargs):
        with tenant_context(self.clinic):
            return scheduling_services.create_appointment(
                clinic=self.clinic,
                patient=self.patient,
                professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1),
                service=self.service,
                **kwargs,
            )

    def test_cancelar_sem_pagamento_cancela_a_conta(self):
        appointment = self._book()
        with tenant_context(self.clinic):
            scheduling_services.change_status(appointment, Appointment.Status.CANCELED)
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.status, FinancialStatus.CANCELED)

    def test_cancelar_com_pagamento_e_manter_nao_gera_estorno(self):
        appointment = self._book(payment_method=self.method, pay_now=True)
        with tenant_context(self.clinic):
            scheduling_services.change_status(
                appointment, Appointment.Status.CANCELED, payment_disposition="",
            )
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            self.assertEqual(receivable.status, FinancialStatus.PAID)
            self.assertFalse(
                FinancialTransaction.objects.filter(
                    receivable=receivable, kind=FinancialTransaction.Kind.REFUND
                ).exists()
            )

    def test_cancelar_com_pagamento_e_estorno_gera_transacao_de_estorno(self):
        appointment = self._book(payment_method=self.method, pay_now=True)
        with tenant_context(self.clinic):
            scheduling_services.change_status(
                appointment, Appointment.Status.CANCELED, payment_disposition="refund",
            )
            receivable = ReceivableAccount.objects.get(appointment=appointment)
            refund = FinancialTransaction.objects.get(
                receivable=receivable, kind=FinancialTransaction.Kind.REFUND
            )
            self.assertEqual(receivable.status, FinancialStatus.REFUNDED)
            self.assertEqual(refund.amount, Decimal("100.00"))
            self.assertEqual(receivable.balance, Decimal("100.00"))


class AppointmentPaymentPermissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.service = make_service(self.clinic, price=Decimal("80.00"))
        self.receptionist = make_receptionist(self.clinic)
        self.admin = make_admin(self.clinic)
        make_financial_category(self.clinic, "income")

    def test_recepcionista_tem_permissao_appointment_payment_por_padrao(self):
        self.assertTrue(self.receptionist.has_clinic_perm("appointment.payment", self.clinic))

    def test_profissional_nao_tem_permissao_appointment_payment_por_padrao(self):
        self.assertFalse(self.user.has_clinic_perm("appointment.payment", self.clinic))

    def test_formulario_de_agendamento_esconde_campos_financeiros_sem_permissao(self):
        form = AppointmentForm(clinic=self.clinic, user=self.user)
        self.assertNotIn("gross_amount", form.fields)
        self.assertFalse(form.can_manage_payment)

    def test_formulario_de_agendamento_mostra_campos_financeiros_com_permissao(self):
        form = AppointmentForm(clinic=self.clinic, user=self.receptionist)
        self.assertIn("gross_amount", form.fields)
        self.assertTrue(form.can_manage_payment)

    def test_recepcionista_acessa_pagamentos_pendentes(self):
        client = Client()
        client.force_login(self.receptionist)
        response = client.get(reverse("finance:pending-payments"))
        self.assertEqual(response.status_code, 200)

    def test_profissional_sem_permissao_recebe_403_em_pagamentos_pendentes(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("finance:pending-payments"))
        self.assertEqual(response.status_code, 403)

    def test_recepcionista_da_baixa_em_pagamento_pendente(self):
        with tenant_context(self.clinic):
            appointment = scheduling_services.create_appointment(
                clinic=self.clinic, patient=self.patient, professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1), service=self.service,
            )
            receivable = ReceivableAccount.objects.get(appointment=appointment)
        method = make_payment_method(self.clinic)
        client = Client()
        client.force_login(self.receptionist)
        response = client.post(
            reverse("finance:appointment-receivable-pay", args=[receivable.pk]),
            {
                "amount": "80.00", "method": str(method.pk),
                "paid_at": timezone.localdate().isoformat(),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        with tenant_context(self.clinic):
            receivable.refresh_from_db()
            self.assertEqual(receivable.status, FinancialStatus.PAID)

    def test_profissional_sem_permissao_nao_consegue_dar_baixa(self):
        with tenant_context(self.clinic):
            appointment = scheduling_services.create_appointment(
                clinic=self.clinic, patient=self.patient, professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1), service=self.service,
            )
            receivable = ReceivableAccount.objects.get(appointment=appointment)
        method = make_payment_method(self.clinic)
        client = Client()
        client.force_login(self.user)
        response = client.post(
            reverse("finance:appointment-receivable-pay", args=[receivable.pk]),
            {
                "amount": "80.00", "method": str(method.pk),
                "paid_at": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 403)
        with tenant_context(self.clinic):
            receivable.refresh_from_db()
            self.assertEqual(receivable.status, FinancialStatus.PENDING)


class PaymentBadgeTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.service = make_service(self.clinic, price=Decimal("60.00"))
        self.method = make_payment_method(self.clinic)
        make_financial_category(self.clinic, "income")

    def test_badge_pago_apos_pagamento_integral(self):
        with tenant_context(self.clinic):
            appointment = scheduling_services.create_appointment(
                clinic=self.clinic, patient=self.patient, professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1), service=self.service,
                payment_method=self.method, pay_now=True,
            )
            self.assertEqual(appointment.payment_badge.get("label"), "Pago")

    def test_badge_pendente_sem_pagamento(self):
        with tenant_context(self.clinic):
            appointment = scheduling_services.create_appointment(
                clinic=self.clinic, patient=self.patient, professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1), service=self.service,
            )
            self.assertEqual(appointment.payment_badge.get("label"), "Pendente")

    def test_sem_conta_financeira_nao_tem_badge(self):
        with tenant_context(self.clinic):
            appointment = scheduling_services.create_appointment(
                clinic=self.clinic, patient=self.patient, professional=self.professional,
                start_at=timezone.now() + timezone.timedelta(days=1),
            )
            self.assertEqual(appointment.payment_badge, {})
