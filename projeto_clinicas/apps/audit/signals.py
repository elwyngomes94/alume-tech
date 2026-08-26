"""
Auditoria automatica de criacao, alteracao e exclusao.

Modelos listados em ``AUDITED_MODELS`` sao auditados sem necessidade de codigo
extra nas views. Visualizacoes continuam sendo registradas explicitamente
(``log_view``), pois dependem do contexto da tela.
"""
from __future__ import annotations

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.audit.models import AuditAction
from apps.audit.services import diff_instance, log_action

AUDITED_MODELS = {
    "accounts.User",
    "accounts.Role",
    "tenants.ClinicMembership",
    "tenants.Organization",
    "clinics.Clinic",
    "clinics.ClinicSettings",
    "clinics.Specialty",
    "clinics.Service",
    "clinics.Room",
    "clinics.InsurancePlan",
    "patients.Patient",
    "professionals.Professional",
    "scheduling.Appointment",
    "scheduling.ScheduleBlock",
    "medical_records.MedicalRecord",
    "medical_records.MedicalRecordEntry",
    "medical_records.Prescription",
    "examinations.ExaminationRequest",
    "examinations.ExaminationResult",
    "documents.Document",
    "lgpd.Consent",
    "lgpd.DataSubjectRequest",
    "billing.Subscription",
    "billing.SystemExpense",
    "finance.ReceivableAccount",
    "finance.PayableAccount",
    "finance.FinancialTransaction",
    "finance.ProfessionalCommissionRule",
    "finance.FinancialCategory",
    "finance.CostCenter",
    "finance.PaymentMethod",
}

#: Campos ignorados na comparacao (ruido ou segredo).
IGNORED_FIELDS = {
    "updated_at",
    "created_at",
    "password",
    "last_login",
    "mfa_secret",
    "key_hash",
    "failed_login_count",
}

SETTINGS_MODELS = {"clinics.ClinicSettings", "accounts.Role", "tenants.ClinicMembership"}


def _tracked_fields(instance):
    return [
        field.attname
        for field in instance._meta.concrete_fields
        if field.attname not in IGNORED_FIELDS
    ]


@receiver(pre_save)
def capture_previous_state(sender, instance, **kwargs):
    label = sender._meta.label if hasattr(sender, "_meta") else ""
    if label not in AUDITED_MODELS or instance.pk is None:
        return
    try:
        old = sender._base_manager.filter(pk=instance.pk).first()
    except Exception:  # pragma: no cover
        old = None
    if old is not None:
        instance._audit_old = {field: getattr(old, field, None) for field in _tracked_fields(old)}


@receiver(post_save)
def audit_save(sender, instance, created, **kwargs):
    label = sender._meta.label if hasattr(sender, "_meta") else ""
    if label not in AUDITED_MODELS:
        return

    if created:
        log_action(
            AuditAction.CREATE,
            obj=instance,
            description=f"{instance._meta.verbose_name} criado(a)",
        )
        return

    old_values = getattr(instance, "_audit_old", None)
    changes = diff_instance(old_values, instance, _tracked_fields(instance)) if old_values else {}

    # Exclusao logica e registrada como DELETE
    if changes.get("is_deleted", {}).get("para") == "True":
        log_action(
            AuditAction.DELETE,
            obj=instance,
            description=f"{instance._meta.verbose_name} excluido(a) logicamente",
            changes=changes,
        )
        return

    if not changes:
        return

    action = (
        AuditAction.SETTINGS_CHANGE
        if label in SETTINGS_MODELS
        else AuditAction.UPDATE
    )
    if label == "tenants.ClinicMembership" and (
        "role" in changes or "extra_permissions" in changes or "denied_permissions" in changes
    ):
        action = AuditAction.PERMISSION_CHANGE

    log_action(
        action,
        obj=instance,
        description=f"{instance._meta.verbose_name} alterado(a)",
        changes=changes,
    )


@receiver(post_delete)
def audit_delete(sender, instance, **kwargs):
    label = sender._meta.label if hasattr(sender, "_meta") else ""
    if label not in AUDITED_MODELS:
        return
    log_action(
        AuditAction.DELETE,
        obj=instance,
        description=f"{instance._meta.verbose_name} removido(a) definitivamente",
    )
