"""Painel do administrador da plataforma: organizacoes, clinicas, usuarios e
o teto de modulos definido pelo plano (RequireModuleMixin)."""
from __future__ import annotations

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.permissions import Roles
from apps.clinics.forms import ClinicForm
from tests.factories import (
    make_admin,
    make_clinic,
    make_organization,
    make_plan,
    make_receptionist,
    make_subscription,
    make_user,
)


def _superadmin() -> "User":  # noqa: F821 - so para tipagem no docstring
    return make_user(role=Roles.SUPERADMIN, is_superuser=True, is_staff=True)


class OrganizationCrudTests(TestCase):
    def setUp(self):
        self.admin = _superadmin()
        self.client = Client()
        self.client.force_login(self.admin)

    def test_criar_organizacao(self):
        response = self.client.post(
            reverse("platform:organization-create"),
            {
                "name": "Grupo Saude Nordeste",
                "trade_name": "",
                "document": "",
                "contact_email": "",
                "contact_phone": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        from apps.tenants.models import Organization

        self.assertTrue(Organization.objects.filter(name="Grupo Saude Nordeste").exists())

    def test_detalhe_agrega_clinicas_usuarios_e_pacientes(self):
        org = make_organization(name="Grupo Teste")
        clinic_a = make_clinic(trade_name="Clinica A", organization=org)
        clinic_b = make_clinic(trade_name="Clinica B", organization=org)
        make_admin(clinic_a)
        make_admin(clinic_b)

        response = self.client.get(reverse("platform:organization-detail", args=[org.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["clinics"]), 2)
        self.assertEqual(response.context["total_users"], 2)

    def test_associar_e_remover_clinica(self):
        org = make_organization(name="Grupo Associacao")
        clinic = make_clinic(trade_name="Clinica Solta")
        self.assertIsNone(clinic.organization_id)

        response = self.client.post(
            reverse("platform:organization-add-clinic", args=[org.pk]),
            {"clinic": str(clinic.pk)},
        )
        self.assertEqual(response.status_code, 302)
        clinic.refresh_from_db()
        self.assertEqual(clinic.organization_id, org.pk)

        response = self.client.post(
            reverse("platform:organization-remove-clinic", args=[org.pk, clinic.pk])
        )
        self.assertEqual(response.status_code, 302)
        clinic.refresh_from_db()
        self.assertIsNone(clinic.organization_id)


class ClinicListModernizationTests(TestCase):
    def setUp(self):
        self.admin = _superadmin()
        self.client = Client()
        self.client.force_login(self.admin)

    def test_lista_mostra_resumo_e_anotacoes(self):
        clinic = make_clinic(trade_name="Clinica Resumo")
        make_admin(clinic)
        response = self.client.get(reverse("platform:clinic-list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("summary", response.context)
        self.assertGreaterEqual(response.context["summary"]["total"], 1)
        clinics = {c.pk: c for c in response.context["clinics"]}
        self.assertEqual(clinics[clinic.pk].total_users, 1)

    def test_filtro_por_plano(self):
        plan = make_plan(name="Plano Filtro")
        clinic_with_plan = make_clinic(trade_name="Com Plano")
        make_subscription(clinic_with_plan, plan)
        make_clinic(trade_name="Sem Plano")

        response = self.client.get(reverse("platform:clinic-list"), {"plan": str(plan.pk)})
        pks = {c.pk for c in response.context["clinics"]}
        self.assertEqual(pks, {clinic_with_plan.pk})


class UserListGroupingTests(TestCase):
    def setUp(self):
        self.admin = _superadmin()
        self.client = Client()
        self.client.force_login(self.admin)

    def test_filtro_por_clinica_mostra_so_os_vinculos_dela(self):
        clinic_a = make_clinic(trade_name="Clinica Usuarios A")
        clinic_b = make_clinic(trade_name="Clinica Usuarios B")
        make_admin(clinic_a)
        make_admin(clinic_b)

        response = self.client.get(reverse("platform:user-list"), {"clinic": str(clinic_a.pk)})
        self.assertEqual(response.status_code, 200)
        clinics_shown = {m.clinic_id for m in response.context["memberships"]}
        self.assertEqual(clinics_shown, {clinic_a.pk})


class PlanModuleCeilingTests(TestCase):
    """
    O item mais critico do pedido: o plano vira o teto dos modulos que a
    clinica pode habilitar, com bloqueio real no backend -- nao so
    escondendo o item do menu.
    """

    def setUp(self):
        self.admin = _superadmin()
        self.client = Client()
        self.client.force_login(self.admin)

    def test_form_da_clinica_so_oferece_modulos_do_plano(self):
        plan = make_plan(name="Plano Sem Estoque", modules=["finance"])
        clinic = make_clinic(trade_name="Clinica Sem Estoque")
        make_subscription(clinic, plan)

        form = ClinicForm(instance=clinic)
        codes = [code for code, _label in form.fields["modules"].choices]
        self.assertIn("finance", codes)
        self.assertNotIn("inventory", codes)

    def test_salvar_corta_modulo_fora_do_plano_mesmo_forcado_no_post(self):
        plan = make_plan(name="Plano Restrito", modules=["finance"])
        clinic = make_clinic(trade_name="Clinica Restrita")
        make_subscription(clinic, plan)

        form = ClinicForm(
            data={
                "legal_name": clinic.legal_name,
                "trade_name": clinic.trade_name,
                "document": clinic.document,
                "clinic_type": clinic.clinic_type,
                "status": clinic.status,
                "modules": ["finance", "inventory"],
            },
            instance=clinic,
        )
        # "inventory" nem aparece nos choices (plano nao permite) -- o
        # ChoiceField ja rejeita no is_valid(), especificamente no campo
        # "modules" (nao por outro motivo qualquer).
        self.assertFalse(form.is_valid())
        self.assertIn("modules", form.errors)

    def test_clinica_sem_inventory_no_plano_e_bloqueada_mesmo_com_permissao(self):
        plan = make_plan(name="Plano Basico", modules=["finance"])
        clinic = make_clinic(trade_name="Clinica Bloqueada", modules=["finance"])
        make_subscription(clinic, plan)
        user = make_admin(clinic)  # CLINIC_ADMIN ja tem todas as permissoes

        client = Client()
        client.force_login(user)
        response = client.get(reverse("inventory:product-list"))
        self.assertEqual(response.status_code, 403)
        self.assertIn("nao esta disponivel no plano", str(response.content))

    def test_clinica_com_inventory_no_plano_acessa_normalmente(self):
        plan = make_plan(name="Plano Com Estoque", modules=["finance", "inventory"])
        clinic = make_clinic(trade_name="Clinica Liberada", modules=["finance", "inventory"])
        make_subscription(clinic, plan)
        user = make_admin(clinic)

        client = Client()
        client.force_login(user)
        response = client.get(reverse("inventory:product-list"))
        self.assertEqual(response.status_code, 200)
