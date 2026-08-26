"""Testes do prontuario eletronico: modelo dinamico, assinatura e retificacao."""
from __future__ import annotations

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.medical_records import services
from apps.medical_records.models import (
    CIDCode,
    MedicalRecordEntry,
    Prescription,
    RecordTemplate,
    VitalSigns,
)
from tests.factories import make_clinic, make_patient, make_professional_user

SIMPLE_SCHEMA = {
    "sections": [
        {
            "title": "Anamnese",
            "fields": [
                {"name": "queixa", "label": "Queixa principal", "type": "textarea",
                 "required": True},
            ],
        }
    ]
}


class MedicalRecordTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        with tenant_context(self.clinic):
            self.template = RecordTemplate.objects.create(
                name="Consulta simples", schema=SIMPLE_SCHEMA, is_default=True
            )

    def test_registro_criado_como_rascunho_pode_ser_assinado(self):
        with tenant_context(self.clinic):
            record = services.get_or_create_record(self.patient)
            entry = MedicalRecordEntry.objects.create(
                record=record,
                professional=self.professional,
                template=self.template,
                data={"queixa": "dor de cabeca"},
                attended_at=timezone.now(),
            )
            self.assertTrue(entry.is_draft)
            entry.sign(self.user)
        entry.refresh_from_db()
        self.assertFalse(entry.is_draft)
        self.assertIsNotNone(entry.signed_at)
        self.assertTrue(entry.signature_hash)

    def test_edicao_apos_assinatura_gera_nova_versao_no_historico(self):
        with tenant_context(self.clinic):
            record = services.get_or_create_record(self.patient)
            entry = MedicalRecordEntry.objects.create(
                record=record, professional=self.professional, template=self.template,
                data={"queixa": "dor"}, attended_at=timezone.now(),
            )
            entry.sign(self.user)
            entry.snapshot(self.user, reason="Correcao de digitacao")
            entry.data = {"queixa": "dor abdominal"}
            entry.save()
            revisions_count = entry.revisions.count()

        self.assertEqual(revisions_count, 1)
        self.assertEqual(entry.version, 2)

    def test_paciente_isolado_por_clinica_no_prontuario(self):
        other_clinic = make_clinic()
        other_patient = make_patient(other_clinic)
        with tenant_context(other_clinic):
            other_record = services.get_or_create_record(other_patient)
        with tenant_context(self.clinic):
            ids = set(MedicalRecordEntry.objects.values_list("record_id", flat=True))
        self.assertNotIn(other_record.pk, ids)

    def test_ensure_default_templates_cria_modelos_do_tipo_da_clinica(self):
        medical_clinic = make_clinic()
        from apps.clinics.modules import ClinicType

        medical_clinic.clinic_type = ClinicType.PHYSIOTHERAPY
        medical_clinic.save(update_fields=["clinic_type"])
        created = services.ensure_default_templates(medical_clinic)
        self.assertGreater(created, 0)
        with tenant_context(medical_clinic):
            self.assertTrue(RecordTemplate.objects.filter(is_default=True).exists())


class VitalSignsTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        with tenant_context(self.clinic):
            self.template = RecordTemplate.objects.create(
                name="Consulta simples", schema=SIMPLE_SCHEMA, is_default=True
            )
            self.record = services.get_or_create_record(self.patient)
            self.entry = MedicalRecordEntry.objects.create(
                record=self.record, professional=self.professional, template=self.template,
                data={"queixa": "dor"}, attended_at=timezone.now(),
            )

    def test_imc_calculado_automaticamente(self):
        with tenant_context(self.clinic):
            vitals = VitalSigns.objects.create(
                entry=self.entry, weight_kg=Decimal("80.00"), height_cm=160,
            )
        self.assertEqual(vitals.bmi, Decimal("31.2"))
        self.assertEqual(vitals.bmi_classification, "Obesidade grau I")

    def test_imc_vazio_sem_peso_ou_altura(self):
        with tenant_context(self.clinic):
            vitals = VitalSigns.objects.create(entry=self.entry, heart_rate=80)
        self.assertIsNone(vitals.bmi)
        self.assertEqual(vitals.bmi_classification, "")

    def test_sinais_vitais_isolados_por_clinica(self):
        with tenant_context(self.clinic):
            VitalSigns.objects.create(entry=self.entry, heart_rate=70)
        other_clinic = make_clinic()
        with tenant_context(other_clinic):
            self.assertEqual(VitalSigns.objects.count(), 0)


class CIDCodeSearchTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.user, _ = make_professional_user(self.clinic)
        CIDCode.objects.get_or_create(code="I10", defaults={"description": "Hipertensao essencial"})

    def test_busca_por_codigo_retorna_resultado(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("medical_records:cid-search"), {"q": "I10"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any(item["id"] == "I10" for item in data["results"]))

    def test_busca_curta_nao_retorna_resultados(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("medical_records:cid-search"), {"q": "I"})
        self.assertEqual(response.json()["results"], [])


class PrescriptionKindTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)

    def test_novos_tipos_de_documento_sao_aceitos(self):
        with tenant_context(self.clinic):
            for kind in (
                Prescription.Kind.DECLARATION,
                Prescription.Kind.REFERRAL,
                Prescription.Kind.CLINICAL_REPORT,
            ):
                prescription = Prescription.objects.create(
                    patient=self.patient, professional=self.professional, kind=kind,
                    content="Item unico",
                )
                self.assertEqual(prescription.kind, kind)
