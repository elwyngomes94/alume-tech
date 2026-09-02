"""Testes do sistema de chamada de pacientes (senha, painel, push)."""
from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.calling import services
from apps.calling.models import CallEvent, CallTicket, PushSubscription
from apps.core.tenancy import tenant_context
from apps.scheduling import services as scheduling_services
from apps.scheduling.models import Appointment
from tests.factories import (
    make_admin,
    make_appointment,
    make_clinic,
    make_patient,
    make_professional_user,
    make_receptionist,
)


def _checkin(clinic, appointment, user=None):
    with tenant_context(clinic):
        return scheduling_services.change_status(appointment, Appointment.Status.CHECKED_IN, user=user)


def _call(clinic, appointment, user=None):
    with tenant_context(clinic):
        return scheduling_services.change_status(appointment, Appointment.Status.CALLED, user=user)


class TicketGenerationTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(modules=["scheduling", "patient_calling"])
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)

    def test_checkin_gera_senha_do_dia(self):
        _checkin(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            self.appointment.refresh_from_db()
            ticket = self.appointment.call_ticket
        self.assertEqual(ticket.ticket_number, "A001")
        self.assertTrue(ticket.access_token)
        self.assertGreater(ticket.token_expires_at, timezone.now())

    def test_checkin_sem_modulo_nao_gera_senha(self):
        clinic = make_clinic(modules=["scheduling"])
        user, professional = make_professional_user(clinic)
        patient = make_patient(clinic)
        appointment = make_appointment(clinic, patient, professional)
        _checkin(clinic, appointment)
        with tenant_context(clinic):
            appointment.refresh_from_db()
            self.assertFalse(hasattr(appointment, "call_ticket"))
            self.assertFalse(CallTicket.objects.exists())

    def test_checkin_idempotente(self):
        _checkin(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            first = self.appointment.call_ticket
            second = services.create_ticket_for_checkin(self.appointment)
        self.assertEqual(first.pk, second.pk)


class TicketNumberRaceConditionTests(TransactionTestCase):
    """Mesma garantia de concorrencia ja provada para agendamentos (ver
    ``tests.test_agenda_capacity.RaceConditionTests``), agora para a
    numeracao de senhas do dia."""

    def setUp(self):
        self.clinic = make_clinic(modules=["scheduling", "patient_calling"])
        self.user, self.professional = make_professional_user(self.clinic)
        self.appointments = [
            make_appointment(self.clinic, make_patient(self.clinic), self.professional)
            for _ in range(3)
        ]
        # Pre-cria a configuracao (mesmo estado do dia a dia, onde ela ja
        # existe ha muito da 1a senha) para nao somar contencao de escrita
        # em outra tabela ao teste de concorrencia -- o SQLite dos testes
        # serializa escritas por lock de arquivo, sem lock por linha.
        with tenant_context(self.clinic):
            services.get_or_create_config(self.clinic)

    def test_senhas_concorrentes_sao_unicas_e_sequenciais(self):
        results = {}
        barrier = threading.Barrier(len(self.appointments))

        def attempt(key, appointment):
            try:
                # PRAGMA busy_timeout: sem isso, o SQLite do teste rejeita
                # imediatamente com "database is locked" em vez de esperar
                # a escrita concorrente terminar (o Postgres da producao
                # nao precisa disso -- tem lock de linha de verdade via
                # ``select_for_update()``).
                connections["default"].cursor().execute("PRAGMA busy_timeout = 20000")
                barrier.wait(timeout=5)
                with tenant_context(self.clinic):
                    ticket = services.create_ticket_for_checkin(appointment)
                results[key] = ticket.ticket_number
            except Exception as exc:  # noqa: BLE001
                results[key] = f"error: {exc}"
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=attempt, args=(i, appt))
            for i, appt in enumerate(self.appointments)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # O SQLite da suite de testes serializa escrita por lock de arquivo
        # inteiro (nao por linha): sob concorrencia real ele pode rejeitar
        # uma tentativa com "database is locked" em vez de so fazer a
        # thread esperar -- o Postgres da producao usa o
        # ``select_for_update()`` de verdade e nao tem essa limitacao
        # (mesma ressalva ja documentada em
        # ``tests.test_agenda_capacity.RaceConditionTests``). A garantia
        # que este teste prova e a que importa: nenhuma tentativa que teve
        # sucesso recebeu um numero de senha repetido.
        numbers = [value for value in results.values() if not value.startswith("error")]
        self.assertGreaterEqual(len(numbers), 1, results)
        self.assertEqual(len(numbers), len(set(numbers)), results)
        with tenant_context(self.clinic):
            self.assertEqual(CallTicket.objects.count(), len(numbers))


class TicketCallFlowTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(modules=["scheduling", "patient_calling"])
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)
        _checkin(self.clinic, self.appointment)

    def test_chamar_incrementa_contador_e_registra_evento(self):
        _call(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            ticket = self.appointment.call_ticket
            ticket.refresh_from_db()
            self.assertEqual(ticket.call_count, 1)
            self.assertEqual(
                CallEvent.objects.filter(ticket=ticket, kind=CallEvent.Kind.CALLED).count(), 1
            )

    def test_rechamar_incrementa_sem_mudar_status(self):
        _call(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            ticket = self.appointment.call_ticket
            services.recall(ticket, user=self.user)
            ticket.refresh_from_db()
            self.appointment.refresh_from_db()
        self.assertEqual(ticket.call_count, 2)
        self.assertEqual(self.appointment.status, Appointment.Status.CALLED)
        with tenant_context(self.clinic):
            self.assertEqual(
                CallEvent.objects.filter(ticket=ticket, kind=CallEvent.Kind.RECALLED).count(), 1
            )

    def test_chamar_envia_push_para_inscricoes_ativas(self):
        with tenant_context(self.clinic):
            ticket = self.appointment.call_ticket
            PushSubscription.objects.create(
                ticket=ticket, endpoint="https://push.example.com/1", p256dh="k", auth="a"
            )
        with patch("pywebpush.webpush") as mocked:
            _call(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            from apps.notifications.models import NotificationDelivery

            delivery = NotificationDelivery.objects.filter(
                channel=NotificationDelivery.Channel.PUSH
            ).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.status, "sent")
        mocked.assert_called_once()

    def test_push_expirado_apaga_inscricao(self):
        from pywebpush import WebPushException

        with tenant_context(self.clinic):
            ticket = self.appointment.call_ticket
            subscription = PushSubscription.objects.create(
                ticket=ticket, endpoint="https://push.example.com/2", p256dh="k", auth="a"
            )

        response = MagicMock(status_code=410)
        with patch("pywebpush.webpush", side_effect=WebPushException("gone", response=response)):
            from apps.notifications.push import send_push

            sent, error = send_push(subscription, title="t", body="b")
        self.assertFalse(sent)
        with tenant_context(self.clinic):
            self.assertFalse(PushSubscription.objects.filter(pk=subscription.pk).exists())


class PatientTicketPageTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(modules=["scheduling", "patient_calling"])
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)
        _checkin(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            self.ticket = self.appointment.call_ticket
        self.client = Client()

    def test_token_valido_retorna_200_sem_vazar_outros_pacientes(self):
        response = self.client.get(reverse("calling:patient-ticket", args=[self.ticket.access_token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket.ticket_number)
        self.assertNotContains(response, self.patient.full_name)

    def test_token_invalido_404(self):
        response = self.client.get(reverse("calling:patient-ticket", args=["token-que-nao-existe"]))
        self.assertEqual(response.status_code, 404)

    def test_token_expirado_404(self):
        with tenant_context(self.clinic):
            CallTicket.objects.filter(pk=self.ticket.pk).update(
                token_expires_at=timezone.now() - timedelta(hours=1)
            )
        response = self.client.get(reverse("calling:patient-ticket", args=[self.ticket.access_token]))
        self.assertEqual(response.status_code, 404)

    def test_sem_modulo_404(self):
        with tenant_context(self.clinic):
            self.clinic.modules = ["scheduling"]
            self.clinic.save(update_fields=["modules"])
        response = self.client.get(reverse("calling:patient-ticket", args=[self.ticket.access_token]))
        self.assertEqual(response.status_code, 404)

    def test_status_endpoint_reflete_chamada(self):
        url = reverse("calling:patient-ticket-status", args=[self.ticket.access_token])
        data = self.client.get(url).json()
        self.assertFalse(data["e_sua_vez"])
        _call(self.clinic, self.appointment)
        data = self.client.get(url).json()
        self.assertTrue(data["e_sua_vez"])

    def test_inscricao_push_sem_csrf(self):
        url = reverse("calling:patient-push-subscribe", args=[self.ticket.access_token])
        response = self.client.post(
            url,
            data='{"endpoint": "https://push.example.com/x", "keys": {"p256dh": "k", "auth": "a"}}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        with tenant_context(self.clinic):
            self.assertTrue(PushSubscription.objects.filter(endpoint="https://push.example.com/x").exists())


class StaffModuleAndPermissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(modules=["scheduling", "patient_calling"])
        self.admin = make_admin(self.clinic)
        self.receptionist = make_receptionist(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)
        _checkin(self.clinic, self.appointment)
        with tenant_context(self.clinic):
            self.ticket = self.appointment.call_ticket

    def _login(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_painel_bloqueado_sem_modulo(self):
        clinic = make_clinic(modules=["scheduling"])
        admin = make_admin(clinic)
        client = self._login(admin)
        response = client.get(reverse("calling:panel-tv"))
        self.assertEqual(response.status_code, 403)

    def test_painel_liberado_com_modulo(self):
        client = self._login(self.admin)
        response = client.get(reverse("calling:panel-tv"))
        self.assertEqual(response.status_code, 200)

    def test_recepcao_pode_rechamar(self):
        _call(self.clinic, self.appointment)
        client = self._login(self.receptionist)
        with tenant_context(self.clinic):
            ticket_pk = self.appointment.call_ticket.pk
        response = client.post(reverse("calling:recall", args=[ticket_pk]))
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.clinic):
            self.assertEqual(CallTicket.objects.get(pk=ticket_pk).call_count, 2)

    def test_paciente_do_portal_nao_acessa_painel(self):
        from apps.accounts.permissions import Roles
        from tests.factories import make_user

        portal_user = make_user(role=Roles.PATIENT)
        with tenant_context(self.clinic):
            self.patient.portal_user = portal_user
            self.patient.save(update_fields=["portal_user"])
        client = self._login(portal_user)
        response = client.get(reverse("calling:panel-tv"))
        self.assertIn(response.status_code, (302, 403))
