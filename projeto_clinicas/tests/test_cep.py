"""Preenchimento automatico de endereco por CEP (proxy do ViaCEP)."""
from __future__ import annotations

from unittest.mock import Mock, patch

import requests
from django.test import Client, TestCase
from django.urls import reverse

from tests.factories import make_admin, make_clinic


class CEPLookupTests(TestCase):
    def setUp(self):
        clinic = make_clinic(trade_name="Clinica CEP")
        self.user = make_admin(clinic)
        self.client = Client()
        self.client.force_login(self.user)

    def test_exige_autenticacao(self):
        anon = Client()
        response = anon.get(reverse("cep-lookup", args=["01310100"]))
        self.assertIn(response.status_code, (302, 403))

    def test_cep_com_tamanho_invalido_retorna_400(self):
        response = self.client.get(reverse("cep-lookup", args=["123"]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("CEP invalido", response.json()["detail"])

    @patch("apps.core.views.requests.get")
    def test_cep_valido_retorna_endereco_normalizado(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=lambda: {
                "logradouro": "Avenida Paulista",
                "bairro": "Bela Vista",
                "localidade": "Sao Paulo",
                "uf": "SP",
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        response = self.client.get(reverse("cep-lookup", args=["01310100"]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["street"], "Avenida Paulista")
        self.assertEqual(data["city"], "Sao Paulo")
        self.assertEqual(data["state"], "SP")

    @patch("apps.core.views.requests.get")
    def test_cep_nao_encontrado_retorna_404_com_mensagem_especifica(self, mock_get):
        mock_get.return_value = Mock(status_code=200, json=lambda: {"erro": True})
        mock_get.return_value.raise_for_status = lambda: None
        response = self.client.get(reverse("cep-lookup", args=["00000000"]))
        self.assertEqual(response.status_code, 404)
        self.assertIn("nao encontrado", response.json()["detail"])

    @patch("apps.core.views.requests.get")
    def test_api_indisponivel_retorna_503_com_mensagem_especifica(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("timeout")
        response = self.client.get(reverse("cep-lookup", args=["01310100"]))
        self.assertEqual(response.status_code, 503)
        self.assertIn("Preencha o endereco manualmente", response.json()["detail"])
