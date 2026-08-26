"""Testes de seguranca: uploads, auditoria imutavel e protecao de login."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.permissions import Roles
from apps.accounts.services import is_throttled, register_failed_attempt
from apps.audit.models import AuditAction, AuditLog
from apps.audit.services import log_action
from apps.core.validators import UploadValidator
from tests.factories import make_clinic, make_membership, make_user


class UploadValidatorTests(TestCase):
    def setUp(self):
        self.validator = UploadValidator()

    def test_rejeita_extensao_nao_permitida(self):
        file_obj = SimpleUploadedFile("virus.exe", b"conteudo", content_type="application/x-msdownload")
        with self.assertRaises(ValidationError):
            self.validator(file_obj)

    def test_rejeita_conteudo_que_nao_corresponde_a_extensao(self):
        """Um arquivo .pdf falso (sem a assinatura %PDF-) deve ser bloqueado."""
        file_obj = SimpleUploadedFile("falso.pdf", b"nao e um pdf de verdade",
                                      content_type="application/pdf")
        with self.assertRaises(ValidationError):
            self.validator(file_obj)

    def test_aceita_pdf_valido(self):
        file_obj = SimpleUploadedFile("real.pdf", b"%PDF-1.4 conteudo valido",
                                      content_type="application/pdf")
        self.validator(file_obj)  # nao deve levantar excecao

    def test_rejeita_arquivo_vazio(self):
        file_obj = SimpleUploadedFile("vazio.pdf", b"", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            self.validator(file_obj)


class AuditLogImmutabilityTests(TestCase):
    def test_registro_de_auditoria_nao_pode_ser_alterado(self):
        entry = log_action(AuditAction.LOGIN, description="teste")
        entry.description = "alterado indevidamente"
        with self.assertRaises(PermissionError):
            entry.save()

    def test_registro_de_auditoria_nao_pode_ser_excluido(self):
        entry = log_action(AuditAction.LOGIN, description="teste")
        with self.assertRaises(PermissionError):
            entry.delete()

    def test_checksum_encadeia_com_o_registro_anterior(self):
        first = log_action(AuditAction.LOGIN, description="primeiro")
        second = log_action(AuditAction.LOGIN, description="segundo")
        self.assertEqual(second.previous_checksum, first.checksum)
        self.assertNotEqual(second.checksum, first.checksum)


class BruteForceProtectionTests(TestCase):
    def test_throttle_bloqueia_apos_limite_de_tentativas(self):
        email = "vitima@example.com"
        self.assertFalse(is_throttled(email))
        for _ in range(5):
            register_failed_attempt(email)
        self.assertTrue(is_throttled(email))

    @override_settings(LOGIN_MAX_ATTEMPTS=3)
    def test_login_view_bloqueia_apos_tentativas_invalidas(self):
        clinic = make_clinic()
        user = make_user(role=Roles.CLINIC_ADMIN, email="alvo@example.com")
        make_membership(user, clinic, Roles.CLINIC_ADMIN)
        client = Client()
        for _ in range(3):
            client.post(reverse("accounts:login"), {"username": user.email, "password": "errada"})
        response = client.post(
            reverse("accounts:login"),
            {"username": user.email, "password": "Teste@12345"},
            follow=True,
        )
        # Mesmo com a senha correta, o bloqueio por tentativas deve prevalecer.
        self.assertContains(response, "Muitas tentativas", status_code=200)


class DocumentAccessSecurityTests(TestCase):
    """Documentos privados nunca sao acessiveis sem autenticacao e permissao."""

    def test_download_de_documento_exige_login(self):
        client = Client()
        response = client.get(reverse("documents:download", args=[
            "00000000-0000-0000-0000-000000000000"
        ]))
        self.assertEqual(response.status_code, 302)  # redireciona para login
