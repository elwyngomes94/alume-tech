"""Servicos LGPD: exportacao, anonimizacao e retencao."""
from __future__ import annotations

import hashlib
from typing import Dict

from django.db import transaction
from django.utils import timezone


def build_patient_export(patient) -> Dict:
    """
    Monta o pacote de dados do titular (acesso/portabilidade - art. 18).

    Inclui cadastro, agendamentos, registros clinicos, exames, documentos e
    consentimentos -- todos restritos a clinica do cadastro.
    """
    from apps.documents.models import Document
    from apps.examinations.models import ExaminationRequest
    from apps.lgpd.models import Consent
    from apps.medical_records.models import MedicalRecordEntry
    from apps.scheduling.models import Appointment

    export = {
        "gerado_em": timezone.now().isoformat(),
        "clinica": str(patient.clinic),
        "titular": {
            "prontuario": patient.record_number,
            "nome": patient.full_name,
            "nome_social": patient.social_name,
            "cpf": patient.cpf,
            "rg": patient.rg,
            "nascimento": patient.birth_date.isoformat() if patient.birth_date else None,
            "genero": patient.get_gender_display(),
            "email": patient.email,
            "telefone": patient.phone,
            "celular": patient.mobile,
            "convenio": str(patient.insurance) if patient.insurance_id else None,
            "criado_em": patient.created_at.isoformat(),
        },
        "dados_de_saude": {
            "tipo_sanguineo": patient.blood_type,
            "alergias": patient.allergies,
            "condicoes_cronicas": patient.chronic_conditions,
            "medicamentos_continuos": patient.continuous_medications,
        },
        "enderecos": [
            {
                "tipo": address.get_kind_display(),
                "logradouro": address.street,
                "numero": address.number,
                "bairro": address.district,
                "cidade": address.city,
                "uf": address.state,
                "cep": address.postal_code,
            }
            for address in patient.addresses.all()
        ],
        "agendamentos": [
            {
                "inicio": appointment.start_at.isoformat(),
                "profissional": appointment.professional.display_name,
                "servico": str(appointment.service) if appointment.service_id else None,
                "status": appointment.get_status_display(),
            }
            for appointment in Appointment.objects.filter(patient=patient).select_related(
                "professional", "service"
            )
        ],
        "atendimentos": [
            {
                "data": entry.attended_at.isoformat(),
                "profissional": entry.professional.display_name,
                "modelo": entry.template.name if entry.template_id else "",
                "conteudo": entry.data,
                "assinado_em": entry.signed_at.isoformat() if entry.signed_at else None,
            }
            for entry in MedicalRecordEntry.objects.filter(
                record__patient=patient, is_draft=False
            ).select_related("professional", "template")
        ],
        "exames": [
            {
                "numero": item.number,
                "solicitado_em": item.requested_at.isoformat(),
                "indicacao": item.clinical_indication,
                "itens": [exam.name for exam in item.items.all()],
                "status": item.get_status_display(),
            }
            for item in ExaminationRequest.objects.filter(patient=patient).prefetch_related("items")
        ],
        "documentos": [
            {
                "titulo": document.title,
                "categoria": str(document.category) if document.category_id else "",
                "enviado_em": document.created_at.isoformat(),
                "tamanho": document.human_size,
            }
            for document in Document.objects.filter(patient=patient).select_related("category")
        ],
        "consentimentos": [
            {
                "tipo": consent.consent_type.name,
                "base_legal": consent.consent_type.get_legal_basis_display(),
                "concedido": consent.granted,
                "data": consent.granted_at.isoformat(),
                "revogado_em": consent.revoked_at.isoformat() if consent.revoked_at else None,
            }
            for consent in Consent.objects.filter(patient=patient).select_related("consent_type")
        ],
    }
    return export


@transaction.atomic
def anonymize_patient(patient, user=None, reason: str = "") -> None:
    """
    Anonimiza o cadastro preservando o historico assistencial estatistico.

    Dados clinicos possuem prazo legal de guarda (Resolucao CFM 1.821/2007 e
    normas correlatas), por isso o registro nao e apagado: os identificadores
    diretos sao substituidos por um pseudonimo irreversivel.
    """
    from apps.audit.models import AuditAction
    from apps.audit.services import log_action

    token = hashlib.sha256(f"{patient.pk}{timezone.now()}".encode()).hexdigest()[:12]
    patient.full_name = f"Titular anonimizado {token}"
    patient.social_name = ""
    patient.cpf = ""
    patient.rg = ""
    patient.email = ""
    patient.phone = ""
    patient.mobile = ""
    patient.whatsapp = ""
    patient.guardian_name = ""
    patient.guardian_document = ""
    patient.guardian_phone = ""
    patient.notes = ""
    patient.photo = None
    patient.status = patient.Status.ARCHIVED
    patient.save()

    patient.addresses.all().delete()
    patient.contacts.all().delete()

    if patient.portal_user_id:
        user_obj = patient.portal_user
        user_obj.is_active = False
        user_obj.save(update_fields=["is_active"])

    log_action(
        AuditAction.UPDATE,
        obj=patient,
        description=f"Paciente anonimizado (LGPD). Motivo: {reason}",
        user=user,
        is_sensitive=True,
    )


def retention_report(clinic) -> Dict:
    """Indicadores de retencao para acompanhamento pelo encarregado (DPO)."""
    from datetime import timedelta

    from apps.medical_records.models import MedicalRecordEntry
    from apps.patients.models import Patient

    settings_obj = getattr(clinic, "settings", None)
    years = settings_obj.data_retention_years if settings_obj else 20
    limit = timezone.now() - timedelta(days=365 * years)
    return {
        "retencao_anos": years,
        "pacientes_ativos": Patient.objects.filter(status=Patient.Status.ACTIVE).count(),
        "pacientes_arquivados": Patient.objects.filter(status=Patient.Status.ARCHIVED).count(),
        "registros_fora_do_prazo": MedicalRecordEntry.objects.filter(
            attended_at__lt=limit
        ).count(),
        "limite": limit.date().isoformat(),
    }
