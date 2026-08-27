"""Servicos do painel da plataforma (SUPERADMIN)."""
from __future__ import annotations

from datetime import timedelta
from typing import Tuple

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import Roles
from apps.accounts.services import DEFAULT_INITIAL_PASSWORD
from apps.clinics.models import Clinic, ClinicSettings
from apps.core.tenancy import tenant_context
from apps.tenants.models import ClinicMembership

DEFAULT_DOCUMENT_CATEGORIES = [
    ("Documento administrativo", False, False),
    ("Exame", True, True),
    ("Laudo", True, True),
    ("Receita", True, True),
    ("Termo de consentimento", True, False),
    ("Foto clinica", True, False),
]

DEFAULT_CONSENT_TYPES = [
    (
        "Termo de consentimento para tratamento de dados",
        "consent",
        "Autorizo o tratamento dos meus dados pessoais para finalidades assistenciais e "
        "administrativas, nos termos da Lei 13.709/2018 (LGPD).",
        True,
    ),
    (
        "Termo de consentimento para registro fotografico",
        "consent",
        "Autorizo o registro fotografico do procedimento para acompanhamento clinico.",
        False,
    ),
]


@transaction.atomic
def provision_clinic(clinic: Clinic, *, admin_email: str = "", admin_name: str = "",
                     plan=None) -> Tuple[Clinic, str]:
    """
    Prepara uma clinica recem-criada.

    Cria as configuracoes, os cadastros iniciais, os modelos de prontuario do
    tipo escolhido, a assinatura e (opcionalmente) o administrador local.
    """
    ClinicSettings.objects.get_or_create(clinic=clinic)

    with tenant_context(clinic):
        from apps.documents.models import DocumentCategory
        from apps.lgpd.models import ConsentType
        from apps.medical_records.services import ensure_default_templates

        for name, is_clinical, visible in DEFAULT_DOCUMENT_CATEGORIES:
            DocumentCategory.all_objects.get_or_create(
                clinic=clinic,
                name=name,
                defaults={
                    "is_clinical": is_clinical,
                    "visible_to_patient_default": visible,
                },
            )
        for name, basis, content, required in DEFAULT_CONSENT_TYPES:
            ConsentType.all_objects.get_or_create(
                clinic=clinic,
                name=name,
                version="1.0",
                defaults={
                    "content": content,
                    "legal_basis": basis,
                    "is_required": required,
                },
            )
        ensure_default_templates(clinic)

        from apps.finance.services import provision_finance_defaults

        provision_finance_defaults(clinic)

    if plan is not None:
        from apps.billing.models import Subscription

        Subscription.objects.get_or_create(
            clinic=clinic,
            defaults={
                "plan": plan,
                "status": Subscription.Status.TRIAL,
                "trial_ends_at": timezone.localdate() + timedelta(days=plan.trial_days),
            },
        )

    provisional_password = ""
    if admin_email:
        user = User.objects.filter(email__iexact=admin_email).first()
        if user is None:
            provisional_password = DEFAULT_INITIAL_PASSWORD
            user = User.objects.create_user(
                email=admin_email.lower(),
                password=provisional_password,
                full_name=admin_name or admin_email,
                role=Roles.CLINIC_ADMIN,
                must_change_password=True,
            )
        ClinicMembership.all_objects.update_or_create(
            user=user,
            clinic=clinic,
            defaults={
                "role": Roles.CLINIC_ADMIN,
                "is_active": True,
                "is_default": True,
                "is_deleted": False,
                "job_title": "Administrador da clinica",
            },
        )
    return clinic, provisional_password


def platform_metrics(start=None, end=None) -> dict:
    """Indicadores globais do JJA System."""
    from django.db.models import Count

    from apps.accounts.models import LoginAttempt
    from apps.audit.models import AuditLog
    from apps.core.tenancy import unscoped
    from apps.patients.models import Patient
    from apps.professionals.models import Professional
    from apps.scheduling.models import Appointment

    with unscoped("dashboard global da plataforma"):
        clinics = Clinic.objects.all()
        appointments = Appointment.objects.all()
        if start and end:
            appointments = appointments.filter(
                start_at__date__gte=start, start_at__date__lte=end
            )
        metrics = {
            "clinics_total": clinics.count(),
            "clinics_active": clinics.filter(status=Clinic.Status.ACTIVE).count(),
            "clinics_trial": clinics.filter(status=Clinic.Status.TRIAL).count(),
            "clinics_suspended": clinics.filter(status=Clinic.Status.SUSPENDED).count(),
            "users_total": User.objects.filter(is_active=True).count(),
            "professionals_total": Professional.objects.filter(is_active=True).count(),
            "patients_total": Patient.objects.count(),
            "appointments_total": appointments.count(),
            "appointments_completed": appointments.filter(
                status=Appointment.Status.COMPLETED
            ).count(),
            "appointments_canceled": appointments.filter(
                status=Appointment.Status.CANCELED
            ).count(),
            "appointments_no_show": appointments.filter(
                status=Appointment.Status.NO_SHOW
            ).count(),
            "by_type": list(
                clinics.values("clinic_type").annotate(total=Count("id")).order_by("-total")
            ),
            "failed_logins_24h": LoginAttempt.objects.filter(
                successful=False, created_at__gte=timezone.now() - timedelta(days=1)
            ).count(),
            "denied_events_24h": AuditLog.objects.filter(
                result="denied", created_at__gte=timezone.now() - timedelta(days=1)
            ).count(),
        }
        total = metrics["appointments_total"] or 0
        metrics["utilization_rate"] = (
            round(metrics["appointments_completed"] * 100 / total, 1) if total else 0.0
        )
    return metrics
