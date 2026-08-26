"""
Testes do requisito de seguranca mais importante do sistema:

    Nenhum usuario de uma clinica pode acessar dados de outra clinica.

Cobrem o isolamento em tres camadas: ORM (managers), views (HTTP) e sessao
(troca indevida de tenant).
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.tenancy import tenant_context, unscoped
from apps.patients.models import Patient
from apps.scheduling.models import Appointment
from tests.factories import (
    make_admin,
    make_appointment,
    make_clinic,
    make_patient,
    make_professional_user,
)


class ORMIsolationTests(TestCase):
    """O manager padrao nunca deve vazar dados entre clinicas."""

    def setUp(self):
        self.clinic_a = make_clinic(trade_name="Clinica A")
        self.clinic_b = make_clinic(trade_name="Clinica B")
        self.patient_a = make_patient(self.clinic_a, full_name="Paciente da Clinica A")
        self.patient_b = make_patient(self.clinic_b, full_name="Paciente da Clinica B")

    def test_queryset_sem_tenant_ativo_retorna_vazio(self):
        """Sem contexto de tenant, o ORM falha fechado (retorna none())."""
        self.assertEqual(Patient.objects.count(), 0)

    def test_tenant_a_nao_enxerga_paciente_da_clinica_b(self):
        with tenant_context(self.clinic_a):
            ids = set(Patient.objects.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, ids)
        self.assertNotIn(self.patient_b.pk, ids)

    def test_tenant_b_nao_enxerga_paciente_da_clinica_a(self):
        with tenant_context(self.clinic_b):
            ids = set(Patient.objects.values_list("pk", flat=True))
        self.assertIn(self.patient_b.pk, ids)
        self.assertNotIn(self.patient_a.pk, ids)

    def test_nao_e_possivel_gravar_registro_em_clinica_diferente_da_ativa(self):
        with tenant_context(self.clinic_a):
            with self.assertRaises(PermissionDenied):
                Patient.objects.create(full_name="Tentativa invalida", clinic=self.clinic_b)

    def test_unscoped_permite_acesso_global_para_rotinas_administrativas(self):
        with unscoped("teste administrativo"):
            ids = set(Patient.objects.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, ids)
        self.assertIn(self.patient_b.pk, ids)


class HttpIsolationTests(TestCase):
    """
    Repete o cenario descrito no prompt:

        Usuario Clinica A -> tenta acessar paciente Clinica B -> ACESSO NEGADO

    E o inverso, garantindo que nenhum tenant acessa dados de outro.
    """

    def setUp(self):
        self.clinic_a = make_clinic(trade_name="Clinica A HTTP")
        self.clinic_b = make_clinic(trade_name="Clinica B HTTP")
        self.admin_a = make_admin(self.clinic_a)
        self.admin_b = make_admin(self.clinic_b)
        self.patient_a = make_patient(self.clinic_a, full_name="Paciente A")
        self.patient_b = make_patient(self.clinic_b, full_name="Paciente B")

    def _login(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_usuario_da_clinica_a_nao_acessa_paciente_da_clinica_b(self):
        client = self._login(self.admin_a)
        response = client.get(reverse("patients:detail", args=[self.patient_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_usuario_da_clinica_b_nao_acessa_paciente_da_clinica_a(self):
        client = self._login(self.admin_b)
        response = client.get(reverse("patients:detail", args=[self.patient_a.pk]))
        self.assertEqual(response.status_code, 404)

    def test_usuario_da_clinica_a_acessa_normalmente_seu_proprio_paciente(self):
        client = self._login(self.admin_a)
        response = client.get(reverse("patients:detail", args=[self.patient_a.pk]))
        self.assertEqual(response.status_code, 200)

    def test_listagem_de_pacientes_nao_vaza_entre_clinicas(self):
        client = self._login(self.admin_a)
        response = client.get(reverse("patients:list"))
        content = response.content.decode()
        self.assertIn("Paciente A", content)
        self.assertNotIn("Paciente B", content)

    def test_usuario_nao_consegue_ativar_clinica_sem_vinculo_via_sessao(self):
        """
        Mesmo manipulando a sessao manualmente (equivalente a adulterar a URL),
        o middleware deve reconferir o vinculo no banco antes de ativar o tenant.
        """
        from apps.tenants.middleware import SESSION_CLINIC_KEY

        client = self._login(self.admin_a)
        session = client.session
        session[SESSION_CLINIC_KEY] = str(self.clinic_b.pk)
        session.save()

        response = client.get(reverse("patients:list"))
        content = response.content.decode()
        # O middleware deve ter revertido para a clinica correta do usuario.
        self.assertNotIn("Paciente B", content)

    def test_troca_de_clinica_via_view_exige_vinculo(self):
        client = self._login(self.admin_a)
        response = client.post(reverse("accounts:clinic-switch", args=[self.clinic_b.pk]))
        self.assertEqual(response.status_code, 404)


class ProfessionalRecordAccessTests(TestCase):
    """
    Profissional so acessa prontuario de paciente com vinculo assistencial
    (agendamento ou registro anterior) -- nao apenas por estar na mesma clinica.
    """

    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Vinculo")
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient_com_vinculo = make_patient(self.clinic, full_name="Com vinculo")
        self.patient_sem_vinculo = make_patient(self.clinic, full_name="Sem vinculo")
        make_appointment(self.clinic, self.patient_com_vinculo, self.professional)

    def test_profissional_acessa_paciente_com_agendamento(self):
        from apps.medical_records.services import can_access_patient_record

        with tenant_context(self.clinic):
            self.assertTrue(
                can_access_patient_record(self.user, self.clinic, self.patient_com_vinculo)
            )

    def test_profissional_nao_acessa_paciente_sem_vinculo_assistencial(self):
        from apps.medical_records.services import can_access_patient_record

        with tenant_context(self.clinic):
            self.assertFalse(
                can_access_patient_record(self.user, self.clinic, self.patient_sem_vinculo)
            )
