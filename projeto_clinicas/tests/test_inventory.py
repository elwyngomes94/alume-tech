"""Modulo de estoque: entrada/saida, saldo, isolamento multi-tenant e permissoes."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.inventory import services
from apps.inventory.models import Product
from tests.factories import make_admin, make_clinic, make_receptionist


def _make_product(clinic, **kwargs):
    with tenant_context(clinic):
        defaults = {"name": "Luva descartavel", "unit": "cx", "minimum_stock": Decimal("10")}
        defaults.update(kwargs)
        return Product.objects.create(**defaults)


class StockServiceTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Estoque")
        self.product = _make_product(self.clinic)

    def test_entrada_aumenta_o_estoque_atual(self):
        services.register_entry(self.product, quantity=Decimal("20"), unit_cost=Decimal("5"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("20"))

    def test_saida_diminui_o_estoque_atual(self):
        services.register_entry(self.product, quantity=Decimal("20"))
        services.register_exit(self.product, quantity=Decimal("8"), reason="Uso clinico")
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("12"))

    def test_saida_maior_que_saldo_e_rejeitada(self):
        services.register_entry(self.product, quantity=Decimal("5"))
        with self.assertRaises(ValidationError):
            services.register_exit(self.product, quantity=Decimal("10"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, Decimal("5"))

    def test_quantidade_zero_ou_negativa_e_rejeitada(self):
        with self.assertRaises(ValidationError):
            services.register_entry(self.product, quantity=Decimal("0"))
        with self.assertRaises(ValidationError):
            services.register_exit(self.product, quantity=Decimal("-1"))

    def test_produto_abaixo_do_minimo_e_sinalizado(self):
        services.register_entry(self.product, quantity=Decimal("3"))
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_below_minimum)


class StockIsolationTests(TestCase):
    def setUp(self):
        self.clinic_a = make_clinic(trade_name="Clinica Estoque A")
        self.clinic_b = make_clinic(trade_name="Clinica Estoque B")
        self.admin_a = make_admin(self.clinic_a)
        self.product_a = _make_product(self.clinic_a, name="Produto A")
        self.product_b = _make_product(self.clinic_b, name="Produto B")

    def test_clinica_a_nao_enxerga_produto_da_clinica_b_na_listagem(self):
        client = Client()
        client.force_login(self.admin_a)
        response = client.get(reverse("inventory:product-list"))
        content = response.content.decode()
        self.assertIn("Produto A", content)
        self.assertNotIn("Produto B", content)

    def test_clinica_a_nao_acessa_produto_da_clinica_b_diretamente(self):
        client = Client()
        client.force_login(self.admin_a)
        response = client.get(reverse("inventory:product-update", args=[self.product_b.pk]))
        self.assertEqual(response.status_code, 404)


class StockPermissionTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic(trade_name="Clinica Estoque Permissoes")
        self.receptionist = make_receptionist(self.clinic)
        self.product = _make_product(self.clinic)

    def test_recepcionista_sem_permissao_dedicada_nao_gerencia_estoque(self):
        client = Client()
        client.force_login(self.receptionist)
        response = client.post(
            reverse("inventory:product-create"),
            {"name": "Novo produto", "unit": "un", "minimum_stock": "0", "cost_price": "0"},
        )
        self.assertEqual(response.status_code, 403)

    def test_recepcionista_sem_permissao_dedicada_nao_visualiza_estoque(self):
        client = Client()
        client.force_login(self.receptionist)
        response = client.get(reverse("inventory:product-list"))
        self.assertEqual(response.status_code, 403)
