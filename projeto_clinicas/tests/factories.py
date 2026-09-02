"""Fabricas de objetos usadas pelos testes automatizados."""
from __future__ import annotations

from datetime import time, timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import Roles
from apps.clinics.models import Clinic, Service, Specialty
from apps.core.tenancy import tenant_context
from apps.patients.models import Patient
from apps.professionals.models import Professional
from apps.scheduling.models import Appointment, ScheduleTemplate
from apps.tenants.models import ClinicMembership

_counter = {"value": 0}


def _seq() -> int:
    _counter["value"] += 1
    return _counter["value"]


def make_clinic(**kwargs) -> Clinic:
    n = _seq()
    defaults = {
        "legal_name": f"Clinica Teste {n} Ltda",
        "trade_name": f"Clinica Teste {n}",
        "document": f"{n:014d}",
        "status": Clinic.Status.ACTIVE,
    }
    defaults.update(kwargs)
    return Clinic.objects.create(**defaults)


def make_user(**kwargs) -> User:
    n = _seq()
    defaults = {
        "email": f"user{n}@example.com",
        "full_name": f"Usuario {n}",
        "role": Roles.RECEPTIONIST,
    }
    defaults.update(kwargs)
    password = defaults.pop("password", "Teste@12345")
    user = User(**defaults)
    user.set_password(password)
    user.save()
    return user


def make_membership(user: User, clinic: Clinic, role: str = Roles.CLINIC_ADMIN) -> ClinicMembership:
    return ClinicMembership.objects.create(user=user, clinic=clinic, role=role, is_active=True)


def make_admin(clinic: Clinic) -> User:
    user = make_user(role=Roles.CLINIC_ADMIN)
    make_membership(user, clinic, Roles.CLINIC_ADMIN)
    return user


def make_receptionist(clinic: Clinic) -> User:
    user = make_user(role=Roles.RECEPTIONIST)
    make_membership(user, clinic, Roles.RECEPTIONIST)
    return user


def make_professional_user(clinic: Clinic) -> tuple[User, Professional]:
    user = make_user(role=Roles.PROFESSIONAL)
    make_membership(user, clinic, Roles.PROFESSIONAL)
    with tenant_context(clinic):
        professional = Professional.objects.create(
            user=user, full_name=user.full_name, email=user.email
        )
    return user, professional


def make_patient(clinic: Clinic, **kwargs) -> Patient:
    with tenant_context(clinic):
        n = _seq()
        defaults = {"full_name": f"Paciente {n}", "mobile": "11999990000"}
        defaults.update(kwargs)
        return Patient.objects.create(**defaults)


def make_service(clinic: Clinic, **kwargs) -> Service:
    with tenant_context(clinic):
        n = _seq()
        defaults = {"name": f"Servico {n}", "duration_minutes": 30, "price": 100}
        defaults.update(kwargs)
        return Service.objects.create(**defaults)


def make_schedule(professional: Professional, clinic: Clinic) -> ScheduleTemplate:
    with tenant_context(clinic):
        return ScheduleTemplate.objects.create(
            professional=professional,
            weekday=timezone.localdate().weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59),
            slot_minutes=30,
        )


def make_appointment(clinic: Clinic, patient: Patient, professional: Professional, **kwargs):
    with tenant_context(clinic):
        n = _seq()
        start = timezone.now() + timedelta(days=1, hours=n)
        defaults = {
            "patient": patient,
            "professional": professional,
            "start_at": start,
            "end_at": start + timedelta(minutes=30),
        }
        defaults.update(kwargs)
        return Appointment.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Financeiro
# ---------------------------------------------------------------------------
def make_payment_method(clinic: Clinic, **kwargs):
    from apps.finance.models import PaymentMethod

    with tenant_context(clinic):
        n = _seq()
        defaults = {"name": f"Forma {n}", "kind": PaymentMethod.Kind.PIX}
        defaults.update(kwargs)
        return PaymentMethod.objects.create(**defaults)


def make_financial_category(clinic: Clinic, kind: str = "income", **kwargs):
    from apps.finance.models import FinancialCategory

    with tenant_context(clinic):
        n = _seq()
        defaults = {"name": f"Categoria {n}", "kind": kind}
        defaults.update(kwargs)
        return FinancialCategory.objects.create(**defaults)


def make_cost_center(clinic: Clinic, **kwargs):
    from apps.finance.models import CostCenter

    with tenant_context(clinic):
        n = _seq()
        defaults = {"name": f"Centro de custo {n}"}
        defaults.update(kwargs)
        return CostCenter.objects.create(**defaults)


def make_receivable(clinic: Clinic, patient: Patient, **kwargs):
    from apps.finance.models import ReceivableAccount

    with tenant_context(clinic):
        category = kwargs.pop("category", None) or make_financial_category(clinic, "income")
        defaults = {
            "patient": patient,
            "category": category,
            "due_date": timezone.localdate(),
            "gross_amount": 200,
        }
        defaults.update(kwargs)
        return ReceivableAccount.objects.create(**defaults)


def make_payable(clinic: Clinic, **kwargs):
    from apps.finance.models import PayableAccount

    with tenant_context(clinic):
        category = kwargs.pop("category", None) or make_financial_category(clinic, "expense")
        n = _seq()
        defaults = {
            "supplier_name": f"Fornecedor {n}",
            "description": "Despesa de teste",
            "category": category,
            "due_date": timezone.localdate(),
            "amount": 100,
        }
        defaults.update(kwargs)
        return PayableAccount.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Planos e organizacoes (painel do administrador da plataforma)
# ---------------------------------------------------------------------------
def make_plan(**kwargs):
    from apps.billing.models import Plan

    n = _seq()
    defaults = {"name": f"Plano {n}", "modules": []}
    defaults.update(kwargs)
    return Plan.objects.create(**defaults)


def make_subscription(clinic: Clinic, plan, **kwargs):
    from apps.billing.models import Subscription

    defaults = {"clinic": clinic, "plan": plan, "status": Subscription.Status.ACTIVE}
    defaults.update(kwargs)
    return Subscription.objects.create(**defaults)


def make_organization(**kwargs):
    from apps.tenants.models import Organization

    n = _seq()
    defaults = {"name": f"Organizacao {n}"}
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)
