"""
Politica de senha: minimo de 5 caracteres, sem regras de complexidade,
numeros-apenas permitido, senha inicial literal "12345" com troca obrigatoria
no primeiro acesso.
"""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import DEFAULT_INITIAL_PASSWORD
from tests.factories import make_admin, make_clinic


class PasswordValidatorTests(TestCase):
    def test_senha_numerica_de_5_digitos_e_aceita(self):
        validate_password("12345")  # nao deve levantar ValidationError

    def test_senha_curta_e_rejeitada(self):
        with self.assertRaises(ValidationError):
            validate_password("1234")

    def test_senha_padrao_do_sistema_e_literal_12345(self):
        self.assertEqual(DEFAULT_INITIAL_PASSWORD, "12345")


class FirstLoginForcedPasswordChangeTests(TestCase):
    """Novo usuario recebe "12345" e e obrigado a trocar antes de usar o sistema."""

    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Senha")
        self.admin = make_admin(self.clinic)

    def _login(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_usuario_criado_pelo_admin_recebe_senha_inicial_e_deve_trocar(self):
        client = self._login(self.admin)
        response = client.post(
            reverse("accounts:user-create"),
            {
                "full_name": "Novo Colaborador",
                "email": "novo.colaborador@example.com",
                "cpf": "",
                "phone": "",
                "is_active": "on",
                "role": "receptionist",
                "job_title": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        new_user = User.objects.get(email="novo.colaborador@example.com")
        self.assertTrue(new_user.check_password(DEFAULT_INITIAL_PASSWORD))
        self.assertTrue(new_user.must_change_password)

    def test_usuario_com_must_change_password_e_bloqueado_ate_trocar(self):
        new_client = self._login(self.admin)
        new_client.post(
            reverse("accounts:user-create"),
            {
                "full_name": "Bloqueado Ate Trocar",
                "email": "bloqueado@example.com",
                "cpf": "",
                "phone": "",
                "is_active": "on",
                "role": "receptionist",
                "job_title": "",
            },
        )
        new_user = User.objects.get(email="bloqueado@example.com")

        client = Client()
        client.force_login(new_user)
        response = client.get(reverse("dashboard:home"), follow=False)
        self.assertRedirects(
            response, reverse("accounts:password-change"), fetch_redirect_response=False
        )

    def test_apos_trocar_a_senha_o_bloqueio_e_liberado(self):
        new_user = User(
            email="troca@example.com", full_name="Troca De Senha", role="receptionist"
        )
        new_user.set_password(DEFAULT_INITIAL_PASSWORD)
        new_user.must_change_password = True
        new_user.save()
        from apps.tenants.models import ClinicMembership

        ClinicMembership.objects.create(
            user=new_user, clinic=self.clinic, role="receptionist", is_active=True
        )

        client = Client()
        client.force_login(new_user)
        response = client.post(
            reverse("accounts:password-change"),
            {
                "old_password": DEFAULT_INITIAL_PASSWORD,
                "new_password1": "novaSenha123",
                "new_password2": "novaSenha123",
            },
        )
        self.assertEqual(response.status_code, 302)
        new_user.refresh_from_db()
        self.assertFalse(new_user.must_change_password)
