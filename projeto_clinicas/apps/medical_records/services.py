"""Regras de acesso e criacao no prontuario."""
from __future__ import annotations

from typing import Optional

from django.core.exceptions import PermissionDenied

from apps.accounts.permissions import Roles
from apps.medical_records.models import MedicalRecord
from apps.medical_records.templates_catalog import templates_for


def get_or_create_record(patient) -> MedicalRecord:
    record = MedicalRecord.objects.filter(patient=patient).first()
    if record is None:
        record = MedicalRecord.objects.create(clinic_id=patient.clinic_id, patient=patient)
    return record


def professional_for(user, clinic):
    from apps.professionals.models import Professional

    return Professional.objects.filter(user=user, clinic=clinic, is_active=True).first()


def can_access_patient_record(user, clinic, patient) -> bool:
    """
    Regra de acesso ao prontuario (principio do minimo necessario).

    * SUPERADMIN: acesso administrativo (sempre auditado);
    * administrador da clinica: acesso a prontuarios da propria clinica;
    * profissional: apenas pacientes com vinculo assistencial (atendimento
      agendado ou registro anterior de sua autoria);
    * recepcao: nao acessa conteudo clinico.
    """
    if patient.clinic_id != clinic.pk:
        return False
    if user.is_superadmin:
        return True
    if not user.has_clinic_perm("medicalrecord.view", clinic):
        return False

    role = user.role_in(clinic)
    if role == Roles.CLINIC_ADMIN:
        return True

    professional = professional_for(user, clinic)
    if professional is None:
        return False

    from apps.medical_records.models import MedicalRecordEntry
    from apps.scheduling.models import Appointment

    has_appointment = Appointment.objects.filter(
        patient=patient, professional=professional
    ).exists()
    has_entry = MedicalRecordEntry.objects.filter(
        record__patient=patient, professional=professional
    ).exists()
    return has_appointment or has_entry


def assert_can_access_patient_record(user, clinic, patient) -> None:
    if not can_access_patient_record(user, clinic, patient):
        raise PermissionDenied(
            "Voce nao possui vinculo assistencial com este paciente nesta clinica."
        )


def ensure_default_templates(clinic) -> int:
    """Cria os modelos de prontuario sugeridos para o tipo da clinica."""
    from apps.medical_records.models import RecordTemplate

    created = 0
    for name, schema, is_default in templates_for(clinic.clinic_type):
        _obj, was_created = RecordTemplate.all_objects.get_or_create(
            clinic=clinic,
            name=name,
            defaults={"schema": schema, "is_default": is_default},
        )
        created += int(was_created)
    return created


def default_template(clinic, professional=None) -> Optional[object]:
    from apps.medical_records.models import RecordTemplate

    queryset = RecordTemplate.objects.filter(is_active=True)
    if professional is not None:
        specialty_ids = list(professional.specialties.values_list("id", flat=True))
        if specialty_ids:
            match = queryset.filter(specialty_id__in=specialty_ids).first()
            if match:
                return match
    return queryset.filter(is_default=True).first() or queryset.first()
