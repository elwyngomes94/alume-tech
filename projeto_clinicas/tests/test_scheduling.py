"""Testes de regras de agendamento: conflitos, bloqueios e transicoes de status."""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.scheduling import services
from apps.scheduling.models import Appointment, ScheduleBlock
from tests.factories import (
    make_admin,
    make_appointment,
    make_clinic,
    make_patient,
    make_professional_user,
    make_schedule,
    make_service,
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

    def test_paciente_nao_pode_ter_dois_atendimentos_no_mesmo_horario(self):
        """Mesmo com profissionais diferentes, o paciente nao pode estar em dois lugares."""
        _other_user, other_professional = make_professional_user(self.clinic)
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            services.create_appointment(
                clinic=self.clinic, patient=self.patient_1,
                professional=self.professional, start_at=start,
            )
            with self.assertRaises(ValidationError) as ctx:
                services.create_appointment(
                    clinic=self.clinic, patient=self.patient_1,
                    professional=other_professional, start_at=start,
                )
        self.assertIn("paciente ja possui", str(ctx.exception).lower())

    def test_conflito_de_paciente_nao_e_contornado_por_encaixe(self):
        """Overbooking existe para profissional/sala -- nunca para o mesmo paciente."""
        _other_user, other_professional = make_professional_user(self.clinic)
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            services.create_appointment(
                clinic=self.clinic, patient=self.patient_1,
                professional=self.professional, start_at=start,
            )
            with self.assertRaises(ValidationError):
                services.create_appointment(
                    clinic=self.clinic, patient=self.patient_1,
                    professional=other_professional, start_at=start,
                    is_overbooking=True,
                )

    def test_mensagem_de_conflito_de_sala_e_especifica(self):
        from apps.clinics.models import Room

        _other_user, other_professional = make_professional_user(self.clinic)
        start = timezone.now() + timedelta(days=1)
        with tenant_context(self.clinic):
            room = Room.objects.create(name="Sala 1", capacity=1)
            services.create_appointment(
                clinic=self.clinic, patient=self.patient_1,
                professional=self.professional, start_at=start, room=room,
            )
            with self.assertRaises(ValidationError) as ctx:
                services.create_appointment(
                    clinic=self.clinic, patient=self.patient_2,
                    professional=other_professional, start_at=start, room=room,
                )
        self.assertIn("sala ja esta ocupada", str(ctx.exception).lower())


class AgendaFilterTests(TestCase):
    """Filtros novos da agenda (servico/sala) -- item H do pedido."""

    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_admin(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        self.service_a = make_service(self.clinic, name="Consulta")
        self.service_b = make_service(self.clinic, name="Retorno")
        self.appointment_a = make_appointment(
            self.clinic, self.patient, self.professional, service=self.service_a
        )
        self.appointment_b = make_appointment(
            self.clinic, self.patient, self.professional, service=self.service_b
        )

    def test_filtro_por_servico_na_lista_da_agenda(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(
            reverse("scheduling:agenda-list"), {"service": str(self.service_a.pk)}
        )
        self.assertEqual(response.status_code, 200)
        appointments = list(response.context["appointments"])
        self.assertIn(self.appointment_a, appointments)
        self.assertNotIn(self.appointment_b, appointments)


class AppointmentFormRendersRequiredHiddenFieldsTests(TestCase):
    """
    Regressao: o campo de busca de paciente/profissional (item A) usa um
    <input type="hidden"> por baixo (AppointmentForm.Meta.widgets) para
    carregar o id de fato enviado no POST. Um bug real de template deixou
    de renderizar esses dois campos ocultos (excluidos do loop generico sem
    um render explicito no lugar), entao a busca aparecia na tela mas nunca
    conseguia de fato selecionar ninguem -- só um teste de HTML renderizado
    pega isso; o Django test client sozinho (sem inspecionar o HTML) não.
    """

    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_admin(self.clinic)

    def test_tela_de_novo_agendamento_renderiza_os_campos_ocultos_de_paciente_e_profissional(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("scheduling:appointment-create"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="id_patient"', content)
        self.assertIn('id="id_professional"', content)
        self.assertIn('data-autocomplete-target="id_patient"', content)
        self.assertIn('data-autocomplete-target="id_professional"', content)


class AgendaEventsApiTests(TestCase):
    """Feed de eventos do calendario visual (item C) -- isolamento e escopo."""

    def setUp(self):
        self.clinic_a = make_clinic(trade_name="Clinica Eventos A")
        self.clinic_b = make_clinic(trade_name="Clinica Eventos B")
        self.admin_a = make_admin(self.clinic_a)
        self.user_a, self.professional_a = make_professional_user(self.clinic_a)
        self.other_user_a, self.other_professional_a = make_professional_user(self.clinic_a)
        self.patient_a = make_patient(self.clinic_a, full_name="Paciente Evento A")
        self.patient_b = make_patient(self.clinic_b, full_name="Paciente Evento B")
        _other_prof_user, professional_b = make_professional_user(self.clinic_b)

        now = timezone.now()
        self.appointment_a = make_appointment(
            self.clinic_a, self.patient_a, self.professional_a,
            start_at=now, end_at=now + timedelta(minutes=30),
        )
        self.appointment_a_other_prof = make_appointment(
            self.clinic_a, self.patient_a, self.other_professional_a,
            start_at=now, end_at=now + timedelta(minutes=30),
        )
        self.appointment_b = make_appointment(
            self.clinic_b, self.patient_b, professional_b,
            start_at=now, end_at=now + timedelta(minutes=30),
        )

    def _range_params(self):
        now = timezone.now()
        return {
            "start": (now - timedelta(days=1)).isoformat(),
            "end": (now + timedelta(days=1)).isoformat(),
        }

    def test_admin_ve_apenas_eventos_da_propria_clinica(self):
        client = Client()
        client.force_login(self.admin_a)
        response = client.get(reverse("scheduling:agenda-events"), self._range_params())
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.json()}
        self.assertIn(str(self.appointment_a.pk), ids)
        self.assertIn(str(self.appointment_a_other_prof.pk), ids)
        self.assertNotIn(str(self.appointment_b.pk), ids)

    def test_profissional_sem_view_all_ve_apenas_os_proprios_eventos(self):
        client = Client()
        client.force_login(self.user_a)
        response = client.get(reverse("scheduling:agenda-events"), self._range_params())
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.json()}
        self.assertIn(str(self.appointment_a.pk), ids)
        self.assertNotIn(str(self.appointment_a_other_prof.pk), ids)


class AppointmentRescheduleAjaxTests(TestCase):
    """Reagendar via arrastar-e-soltar no calendario (item C) -- resposta JSON."""

    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_admin(self.clinic)
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)

    def test_reagendar_via_ajax_com_sucesso_retorna_json(self):
        client = Client()
        client.force_login(self.admin)
        new_start = timezone.now() + timedelta(days=2)
        response = client.post(
            reverse("scheduling:appointment-reschedule", args=[self.appointment.pk]),
            {"start": new_start.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.start_at, new_start)

    def test_reagendar_via_ajax_com_conflito_retorna_erro_json_sem_alterar_o_agendamento(self):
        _other_user, other_professional = make_professional_user(self.clinic)
        conflicting_start = timezone.now() + timedelta(days=3)
        make_appointment(
            self.clinic, self.patient, other_professional,
            start_at=conflicting_start, end_at=conflicting_start + timedelta(minutes=30),
        )
        original_start = self.appointment.start_at

        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse("scheduling:appointment-reschedule", args=[self.appointment.pk]),
            {"start": conflicting_start.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        self.assertIn("paciente ja possui", response.json()["detail"].lower())
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.start_at, original_start)
