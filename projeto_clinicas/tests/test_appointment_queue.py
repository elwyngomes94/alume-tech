"""Status "Chamado" e fila de atendimento da recepcao."""
from __future__ import annotations

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.notifications.models import Notification, NotificationEvent
from apps.scheduling import services
from apps.scheduling.models import Appointment
from tests.factories import (
    make_appointment,
    make_clinic,
    make_patient,
    make_professional_user,
    make_receptionist,
)


class CalledStatusTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Fila")
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic, full_name="Paciente da Fila")
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)

    def test_fluxo_ate_chamado_e_permitido_e_carimba_called_at(self):
        with tenant_context(self.clinic):
            services.change_status(self.appointment, Appointment.Status.CONFIRMED)
            services.change_status(self.appointment, Appointment.Status.CHECKED_IN)
            services.change_status(self.appointment, Appointment.Status.CALLED)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.CALLED)
        self.assertIsNotNone(self.appointment.called_at)

    def test_chamado_permite_seguir_para_em_atendimento(self):
        with tenant_context(self.clinic):
            services.change_status(self.appointment, Appointment.Status.CHECKED_IN)
            services.change_status(self.appointment, Appointment.Status.CALLED)
            services.change_status(self.appointment, Appointment.Status.IN_PROGRESS)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.IN_PROGRESS)
        self.assertIsNotNone(self.appointment.started_at)

    def test_chamado_dispara_notificacao_para_o_profissional(self):
        with tenant_context(self.clinic):
            services.change_status(self.appointment, Appointment.Status.CHECKED_IN)
            services.change_status(self.appointment, Appointment.Status.CALLED)
        exists = Notification.objects.filter(
            recipient=self.user, event=NotificationEvent.APPOINTMENT_CALLED
        ).exists()
        self.assertTrue(exists)


class ReceptionDashboardTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Recepcao")
        self.receptionist = make_receptionist(self.clinic)
        self.prof_user, self.professional = make_professional_user(self.clinic)
        self.patient_waiting = make_patient(self.clinic, full_name="Paciente Aguardando")
        self.patient_in_progress = make_patient(self.clinic, full_name="Paciente Em Atendimento")
        now = timezone.now()
        self.appointment_waiting = make_appointment(
            self.clinic, self.patient_waiting, self.professional,
            start_at=now, end_at=now + timezone.timedelta(minutes=30),
        )
        self.appointment_in_progress = make_appointment(
            self.clinic, self.patient_in_progress, self.professional,
            start_at=now, end_at=now + timezone.timedelta(minutes=30),
        )
        with tenant_context(self.clinic):
            services.change_status(self.appointment_waiting, Appointment.Status.CHECKED_IN)
            services.change_status(
                self.appointment_in_progress, Appointment.Status.CHECKED_IN
            )
            services.change_status(
                self.appointment_in_progress, Appointment.Status.CALLED
            )
            services.change_status(
                self.appointment_in_progress, Appointment.Status.IN_PROGRESS
            )

    def test_painel_destaca_paciente_em_atendimento(self):
        client = Client()
        client.force_login(self.receptionist)
        response = client.get(reverse("dashboard:reception"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("PACIENTE EM ATENDIMENTO", content)
        self.assertIn("Paciente Em Atendimento", content)

    def test_painel_lista_paciente_aguardando_com_botao_chamar(self):
        client = Client()
        client.force_login(self.receptionist)
        response = client.get(reverse("dashboard:reception"))
        content = response.content.decode()
        self.assertIn("Paciente Aguardando", content)
        self.assertIn(
            reverse("scheduling:appointment-status", args=[self.appointment_waiting.pk, "called"]),
            content,
        )
