"""Testes de autorizacao (RBAC) dentro de uma mesma clinica."""
from __future__ import annotations

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.permissions import Roles
from tests.factories import make_clinic, make_membership, make_patient, make_user


class RolePermissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.patient = make_patient(self.clinic)

    def _login(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_recepcionista_pode_ver_pacientes(self):
        user = make_user(role=Roles.RECEPTIONIST)
        make_membership(user, self.clinic, Roles.RECEPTIONIST)
        client = self._login(user)
        response = client.get(reverse("patients:list"))
        self.assertEqual(response.status_code, 200)

    def test_recepcionista_nao_pode_gerenciar_papeis(self):
        user = make_user(role=Roles.RECEPTIONIST)
        make_membership(user, self.clinic, Roles.RECEPTIONIST)
        client = self._login(user)
        response = client.get(reverse("accounts:role-list"))
        self.assertEqual(response.status_code, 403)

    def test_administrador_pode_gerenciar_papeis(self):
        user = make_user(role=Roles.CLINIC_ADMIN)
        make_membership(user, self.clinic, Roles.CLINIC_ADMIN)
        client = self._login(user)
        response = client.get(reverse("accounts:role-list"))
        self.assertEqual(response.status_code, 200)

    def test_usuario_sem_vinculo_nenhum_e_redirecionado(self):
        user = make_user(role=Roles.RECEPTIONIST)
        client = self._login(user)
        response = client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("sem-clinica", response.headers["Location"])

    def test_has_clinic_perm_falha_fechado_sem_clinica(self):
        user = make_user(role=Roles.RECEPTIONIST)
        make_membership(user, self.clinic, Roles.RECEPTIONIST)
        # Sem tenant ativo no contexto, has_clinic_perm deve negar.
        self.assertFalse(user.has_clinic_perm("patient.view"))

    def test_permissao_negada_via_url_manipulada_devolve_403(self):
        """Regra de ouro: alterar a URL nao deve conceder acesso indevido."""
        user = make_user(role=Roles.RECEPTIONIST)
        make_membership(user, self.clinic, Roles.RECEPTIONIST)
        client = self._login(user)
        # Recepcionista nao tem permissao de excluir paciente.
        response = client.post(reverse("patients:delete", args=[self.patient.pk]))
        self.assertEqual(response.status_code, 403)


class SuperadminAccessTests(TestCase):
    def test_superadmin_acessa_painel_da_plataforma(self):
        user = make_user(role=Roles.SUPERADMIN, is_superuser=True, is_staff=True)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("platform:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_usuario_comum_nao_acessa_painel_da_plataforma(self):
        clinic = make_clinic()
        user = make_user(role=Roles.CLINIC_ADMIN)
        make_membership(user, clinic, Roles.CLINIC_ADMIN)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("platform:dashboard"))
        self.assertEqual(response.status_code, 403)
