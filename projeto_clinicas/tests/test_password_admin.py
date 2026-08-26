"""Testes de definicao/redefinicao de senha por um administrador."""
from __future__ import annotations

from django.contrib.auth.hashers import check_password
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import User, UserSession
from apps.accounts.permissions import Roles
from tests.factories import make_admin, make_clinic, make_membership, make_user


class AdminSetPasswordServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_gera_senha_aleatoria_e_forca_troca_por_padrao(self):
        password = services.admin_set_password(self.user)
        self.user.refresh_from_db()
        self.assertTrue(check_password(password, self.user.password))
        self.assertTrue(self.user.must_change_password)

    def test_permite_definir_senha_especifica(self):
        services.admin_set_password(self.user, raw_password="MinhaSenhaForte@2026")
        self.user.refresh_from_db()
        self.assertTrue(check_password("MinhaSenhaForte@2026", self.user.password))

    def test_redefinicao_encerra_sessoes_ativas(self):
        UserSession.objects.create(user=self.user, session_key="abc123")
        services.admin_set_password(self.user)
        session = UserSession.objects.get(user=self.user, session_key="abc123")
        self.assertIsNotNone(session.revoked_at)

    def test_limpa_bloqueio_e_tentativas_anteriores(self):
        from django.utils import timezone

        self.user.locked_until = timezone.now() + timezone.timedelta(hours=1)
        self.user.failed_login_count = 5
        self.user.save()
        services.admin_set_password(self.user)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.assertEqual(self.user.failed_login_count, 0)


class ClinicUserPasswordResetViewTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_admin(self.clinic)
        self.target = make_user(role=Roles.RECEPTIONIST)
        self.membership = make_membership(self.target, self.clinic, Roles.RECEPTIONIST)

    def _login(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_administrador_redefine_senha_gerando_automaticamente(self):
        client = self._login()
        response = client.post(
            reverse("accounts:user-password-reset", args=[self.membership.pk]),
            {"mode": "generate", "force_change": "on"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.must_change_password)

    def test_administrador_define_senha_especifica(self):
        client = self._login()
        response = client.post(
            reverse("accounts:user-password-reset", args=[self.membership.pk]),
            {
                "mode": "manual", "password1": "OutraSenhaForte@2026",
                "password2": "OutraSenhaForte@2026", "force_change": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(check_password("OutraSenhaForte@2026", self.target.password))
        self.assertFalse(self.target.must_change_password)

    def test_senhas_diferentes_sao_rejeitadas(self):
        client = self._login()
        response = client.post(
            reverse("accounts:user-password-reset", args=[self.membership.pk]),
            {"mode": "manual", "password1": "SenhaForte@2026", "password2": "Diferente@2026"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "nao coincidem")

    def test_usuario_sem_permissao_recebe_403(self):
        receptionist_user = make_user(role=Roles.RECEPTIONIST)
        make_membership(receptionist_user, self.clinic, Roles.RECEPTIONIST)
        client = Client()
        client.force_login(receptionist_user)
        response = client.get(
            reverse("accounts:user-password-reset", args=[self.membership.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_nao_pode_redefinir_a_propria_senha_por_aqui(self):
        client = self._login()
        own_membership = self.admin.membership_for(self.clinic)
        response = client.get(
            reverse("accounts:user-password-reset", args=[own_membership.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_nao_pode_redefinir_senha_de_superadmin_pelo_painel_da_clinica(self):
        superadmin = make_user(role=Roles.SUPERADMIN, is_superuser=True, is_staff=True)
        membership = make_membership(superadmin, self.clinic, Roles.CLINIC_ADMIN)
        client = self._login()
        response = client.get(reverse("accounts:user-password-reset", args=[membership.pk]))
        self.assertEqual(response.status_code, 403)

    def test_admin_de_outra_clinica_nao_redefine_senha_via_url_manipulada(self):
        other_clinic = make_clinic()
        other_admin = make_admin(other_clinic)
        client = Client()
        client.force_login(other_admin)
        response = client.get(
            reverse("accounts:user-password-reset", args=[self.membership.pk])
        )
        self.assertEqual(response.status_code, 404)


class PlatformUserPasswordResetViewTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=Roles.SUPERADMIN, is_superuser=True, is_staff=True)
        self.clinic = make_clinic()
        self.target = make_admin(self.clinic)

    def test_superadmin_redefine_senha_de_qualquer_usuario(self):
        client = Client()
        client.force_login(self.superadmin)
        response = client.post(
            reverse("platform:user-password-reset", args=[self.target.pk]),
            {"mode": "generate", "force_change": "on"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.must_change_password)

    def test_admin_de_clinica_nao_acessa_endpoint_do_superadmin(self):
        client = Client()
        client.force_login(self.target)
        response = client.get(
            reverse("platform:user-password-reset", args=[self.superadmin.pk])
        )
        self.assertEqual(response.status_code, 403)
