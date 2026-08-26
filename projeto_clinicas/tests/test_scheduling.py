"""Testes de regras de agendamento: conflitos, bloqueios e transicoes de status."""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.scheduling import services
from apps.scheduling.models import Appointment, ScheduleBlock
from tests.factories import (
    make_appointment,
    make_clinic,
    make_patient,
    make_professional_user,
    make_schedule,
)


class AppointmentConflictTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.user, self.professional = make_professional_user(self.clinic)
        make_schedule(self.professional, self.clinic)
        self.patient_1 = make_patient(self.clinic, full_name="Paciente 1")
        self.patient_2 = make_patient(self.clinic, full_name="Paciente 2")

    def test_nao_permite_dois_agendamentos_no_mesmo_horario(self):
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            services.create_appointment(
                clinic=self.clinic, patient=self.patient_1,
                professional=self.professional, start_at=start,
            )
            with self.assertRaises(ValidationError):
                services.create_appointment(
                    clinic=self.clinic, patient=self.patient_2,
                    professional=self.professional, start_at=start,
                )

    def test_permite_encaixe_quando_marcado_como_overbooking(self):
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            services.create_appointment(
                clinic=self.clinic, patient=self.patient_1,
                professional=self.professional, start_at=start,
            )
            appointment = services.create_appointment(
                clinic=self.clinic, patient=self.patient_2,
                professional=self.professional, start_at=start, is_overbooking=True,
            )
        self.assertTrue(appointment.is_overbooking)

    def test_nao_permite_agendar_sobre_bloqueio(self):
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            ScheduleBlock.objects.create(
                professional=self.professional,
                kind=ScheduleBlock.Kind.ABSENCE,
                start_at=start - timedelta(minutes=10),
                end_at=start + timedelta(hours=1),
            )
            with self.assertRaises(ValidationError):
                services.create_appointment(
                    clinic=self.clinic, patient=self.patient_1,
                    professional=self.professional, start_at=start,
                )

    def test_transicao_de_status_invalida_e_rejeitada(self):
        appointment = make_appointment(self.clinic, self.patient_1, self.professional)
        with tenant_context(self.clinic):
            with self.assertRaises(ValidationError):
                services.change_status(appointment, Appointment.Status.COMPLETED)

    def test_fluxo_completo_de_status_e_permitido(self):
        appointment = make_appointment(self.clinic, self.patient_1, self.professional)
        with tenant_context(self.clinic):
            services.change_status(appointment, Appointment.Status.CONFIRMED)
            services.change_status(appointment, Appointment.Status.CHECKED_IN)
            services.change_status(appointment, Appointment.Status.IN_PROGRESS)
            services.change_status(appointment, Appointment.Status.COMPLETED)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_nao_permite_paciente_de_outra_clinica(self):
        other_clinic = make_clinic()
        other_patient = make_patient(other_clinic)
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            from django.core.exceptions import PermissionDenied

            with self.assertRaises(PermissionDenied):
                services.create_appointment(
                    clinic=self.clinic, patient=other_patient,
                    professional=self.professional, start_at=start,
                )
