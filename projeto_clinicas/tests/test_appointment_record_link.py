"""Vinculo agendamento -> prontuario (botao "Abrir prontuario"), item E do pedido."""
from __future__ import annotations

from django.test import Client, TestCase
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.medical_records.models import MedicalRecordEntry, RecordTemplate
from tests.factories import (
    make_admin,
    make_appointment,
    make_clinic,
    make_patient,
    make_professional_user,
)


class AppointmentRecordLinkTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Prontuario")
        self.admin = make_admin(self.clinic)
        self.prof_user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic, full_name="Paciente Vinculo")
        self.appointment = make_appointment(self.clinic, self.patient, self.professional)
        with tenant_context(self.clinic):
            RecordTemplate.objects.create(name="Padrao", schema={}, is_default=True)

    def _login(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_tela_de_novo_atendimento_preenche_profissional_e_data_do_agendamento(self):
        client = self._login(self.admin)
        response = client.get(
            reverse("medical_records:entry-create", args=[self.patient.pk]),
            {"appointment": str(self.appointment.pk)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["appointment"], self.appointment)
        self.assertEqual(
            response.context["meta_form"].initial.get("professional"), self.professional
        )

    def test_salvar_atendimento_grava_o_vinculo_com_o_agendamento(self):
        client = self._login(self.admin)
        response = client.get(reverse("medical_records:entry-create", args=[self.patient.pk]))
        template = response.context["template_obj"]
        response = client.post(
            reverse("medical_records:entry-create", args=[self.patient.pk]),
            {
                "appointment": str(self.appointment.pk),
                "professional": str(self.professional.pk),
                "template": str(template.pk),
                "attended_at": "2026-01-10T10:00",
                "action": "draft",
            },
        )
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.clinic):
            entry = MedicalRecordEntry.objects.get(record__patient=self.patient)
        self.assertEqual(entry.appointment_id, self.appointment.pk)

    def test_nao_e_possivel_vincular_agendamento_de_outro_paciente(self):
        """
        O id do agendamento vem por querystring/POST -- se alguem manipular
        para o id de um agendamento de OUTRO paciente da mesma clinica, o
        vinculo deve ser ignorado (nao gravado), nunca aceito silenciosamente.
        """
        other_patient = make_patient(self.clinic, full_name="Outro Paciente")
        client = self._login(self.admin)
        response = client.get(
            reverse("medical_records:entry-create", args=[other_patient.pk]),
            {"appointment": str(self.appointment.pk)},
        )
        self.assertIsNone(response.context["appointment"])

    def test_nao_e_possivel_vincular_agendamento_de_outra_clinica(self):
        other_clinic = make_clinic()
        _other_user, other_professional = make_professional_user(other_clinic)
        other_patient = make_patient(other_clinic)
        other_appointment = make_appointment(other_clinic, other_patient, other_professional)

        client = self._login(self.admin)
        response = client.get(
            reverse("medical_records:entry-create", args=[self.patient.pk]),
            {"appointment": str(other_appointment.pk)},
        )
        self.assertIsNone(response.context["appointment"])
