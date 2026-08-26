"""
Testes de contas: cadastro de usuario da clinica e o indicador "is_saved".

Regressao do bug: como o pk usa ``default=uuid.uuid4``, uma instancia recem
instanciada (ainda nao salva) ja possui um ``pk`` preenchido. Codigo que usa
``if instance.pk:`` para decidir "e uma edicao" fica sempre em branco no
"create". O indicador correto e ``instance.is_saved``.
"""
from __future__ import annotations

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.forms import ClinicUserForm
from apps.accounts.models import User
from apps.accounts.permissions import Roles
from tests.factories import make_clinic, make_membership, make_user


class IsSavedPropertyTests(TestCase):
    def test_instancia_nova_nao_persistida_tem_pk_mas_nao_e_saved(self):
        clinic = make_clinic()
        # instanciada mas NUNCA salva
        self.assertIsNotNone(clinic.pk, "precondicao: UUID ja preenchido antes do save")

        from apps.clinics.models import Clinic

        fresh = Clinic(legal_name="X", trade_name="X", document="00000000000000")
        self.assertIsNotNone(fresh.pk)
        self.assertFalse(fresh.is_saved)

    def test_instancia_carregada_do_banco_e_saved(self):
        clinic = make_clinic()
        from apps.clinics.models import Clinic

        loaded = Clinic.objects.get(pk=clinic.pk)
        self.assertTrue(loaded.is_saved)

    def test_user_novo_nao_e_saved_e_apos_save_passa_a_ser(self):
        user = User(email="novo@example.com", full_name="Novo")
        self.assertFalse(user.is_saved)
        user.set_password("Teste@12345")
        user.save()
        self.assertTrue(user.is_saved)


class ClinicUserFormCreateTests(TestCase):
    """Regressao: o campo de e-mail nao pode ficar desabilitado ao criar."""

    def setUp(self):
        self.clinic = make_clinic()

    def test_formulario_de_criacao_nao_desabilita_email(self):
        form = ClinicUserForm(clinic=self.clinic)
        self.assertFalse(form.fields["email"].disabled)

    def test_formulario_de_edicao_desabilita_email(self):
        user = make_user(role=Roles.RECEPTIONIST)
        membership = make_membership(user, self.clinic, Roles.RECEPTIONIST)
        form = ClinicUserForm(instance=user, clinic=self.clinic, membership=membership)
        self.assertTrue(form.fields["email"].disabled)

    def test_criar_usuario_preserva_o_email_informado(self):
        form = ClinicUserForm(
            data={
                "full_name": "Usuario Novo",
                "email": "usuario.novo@example.com",
                "cpf": "",
                "phone": "",
                "is_active": "on",
                "role": Roles.RECEPTIONIST,
                "job_title": "",
            },
            clinic=self.clinic,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "usuario.novo@example.com")


class ClinicUserCreateViewTests(TestCase):
    """Fluxo HTTP completo: administrador cadastra um novo usuario na clinica."""

    def setUp(self):
        self.clinic = make_clinic()
        self.admin = make_user(role=Roles.CLINIC_ADMIN)
        make_membership(self.admin, self.clinic, Roles.CLINIC_ADMIN)

    def test_criar_usuario_via_post_persiste_com_email_correto(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse("accounts:user-create"),
            {
                "full_name": "Recepcionista Nova",
                "email": "recepcionista.nova@example.com",
                "cpf": "",
                "phone": "",
                "is_active": "on",
                "role": Roles.RECEPTIONIST,
                "job_title": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.filter(email="recepcionista.nova@example.com").first()
        self.assertIsNotNone(user, "usuario deveria ter sido criado com o e-mail informado")
        self.assertTrue(user.membership_for(self.clinic) is not None)
