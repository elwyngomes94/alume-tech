"""
Cria dados de demonstracao do JJA System (nao usar em producao).

Gera:
    - 1 superadmin
    - 1 clinica demo (medica) com administrador, recepcionista, profissional
    - 1 clinica demo (fisioterapia) para demonstrar isolamento entre tenants
    - pacientes, servicos, disponibilidade e um plano basico

Uso:
    python manage.py seed_demo
"""
from __future__ import annotations

from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import Roles
from apps.billing.models import Plan
from apps.clinics.models import Clinic, InsurancePlan, Room, Service, Specialty
from apps.clinics.modules import ClinicType
from apps.core.tenancy import tenant_context
from apps.patients.models import Patient
from apps.platform_admin.services import provision_clinic
from apps.professionals.models import Professional
from apps.scheduling.models import ScheduleTemplate
from apps.tenants.models import ClinicMembership

DEMO_PASSWORD = "Demo@12345"


class Command(BaseCommand):
    help = "Cria dados de demonstracao (superadmin, clinicas, usuarios e pacientes ficticios)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Criando dados de demonstracao do JJA System...")

        superadmin = self._create_superadmin()
        plan = self._create_plan()

        medical = self._create_clinic(
            legal_name="Clinica Boa Saude Ltda",
            trade_name="Clinica Boa Saude",
            document="11.111.111/0001-11",
            clinic_type=ClinicType.MEDICAL,
            city="Sao Paulo",
            state="SP",
            plan=plan,
        )
        physio = self._create_clinic(
            legal_name="Espaco Movimento Fisioterapia Ltda",
            trade_name="Espaco Movimento",
            document="22.222.222/0001-22",
            clinic_type=ClinicType.PHYSIOTHERAPY,
            city="Curitiba",
            state="PR",
            plan=plan,
        )

        self._populate_clinic(medical, "medica-demo")
        self._populate_clinic(physio, "fisio-demo")
        self._seed_system_finance([medical, physio])

        self.stdout.write(self.style.SUCCESS("Dados de demonstracao criados com sucesso."))
        self.stdout.write(f"Superadmin: {superadmin.email} / senha: {DEMO_PASSWORD}")
        self.stdout.write(f"Senha padrao de todos os usuarios demo: {DEMO_PASSWORD}")
        self.stdout.write(
            "Use estes dados apenas em ambiente de desenvolvimento/homologacao."
        )

    # ------------------------------------------------------------------
    def _create_superadmin(self) -> User:
        user, created = User.objects.get_or_create(
            email="superadmin@jjasystem.com.br",
            defaults={
                "full_name": "Superadministrador JJA",
                "role": Roles.SUPERADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user

    def _create_plan(self) -> Plan:
        plan, _created = Plan.objects.get_or_create(
            name="Plano Profissional (demo)",
            defaults={
                "tier": Plan.Tier.PROFESSIONAL,
                "monthly_price": 299,
                "yearly_price": 2990,
                "max_professionals": 10,
                "max_users": 20,
                "max_patients": 2000,
                "max_storage_mb": 10240,
                "supports_api": True,
            },
        )
        return plan

    def _create_clinic(self, *, legal_name, trade_name, document, clinic_type, city, state, plan):
        clinic, created = Clinic.all_objects.get_or_create(
            document=document,
            defaults={
                "legal_name": legal_name,
                "trade_name": trade_name,
                "clinic_type": clinic_type,
                "city": city,
                "state": state,
                "status": Clinic.Status.ACTIVE,
                "email": f"contato@{trade_name.lower().replace(' ', '')}.com.br",
                "phone": "11999990000",
            },
        )
        if created:
            provision_clinic(clinic, plan=plan)
        return clinic

    def _populate_clinic(self, clinic: Clinic, slug: str) -> None:
        with tenant_context(clinic):
            specialty, _ = Specialty.all_objects.get_or_create(
                clinic=clinic, name="Clinica geral", defaults={"color": "#0b5ed7"}
            )
            service, _ = Service.all_objects.get_or_create(
                clinic=clinic,
                name="Consulta",
                defaults={"specialty": specialty, "duration_minutes": 30, "price": 150},
            )
            room, _ = Room.all_objects.get_or_create(clinic=clinic, name="Sala 1")
            InsurancePlan.all_objects.get_or_create(clinic=clinic, name="Particular")

            admin_user = self._create_membership(
                clinic, f"admin.{slug}@jjasystem.com.br", "Administrador", Roles.CLINIC_ADMIN
            )
            self._create_membership(
                clinic, f"recepcao.{slug}@jjasystem.com.br", "Recepcionista",
                Roles.RECEPTIONIST,
            )
            professional_user = self._create_membership(
                clinic, f"profissional.{slug}@jjasystem.com.br", "Dr(a). Profissional",
                Roles.PROFESSIONAL,
            )

            professional, _ = Professional.all_objects.get_or_create(
                clinic=clinic,
                user=professional_user,
                defaults={
                    "full_name": professional_user.full_name,
                    "email": professional_user.email,
                    "council": "CRM",
                    "registry_number": "123456",
                    "registry_state": clinic.state,
                },
            )
            professional.specialties.add(specialty)
            professional.services.add(service)
            professional.rooms.add(room)

            for weekday in range(5):  # segunda a sexta
                ScheduleTemplate.all_objects.get_or_create(
                    clinic=clinic,
                    professional=professional,
                    weekday=weekday,
                    defaults={
                        "start_time": time(8, 0),
                        "end_time": time(18, 0),
                        "slot_minutes": 30,
                        "break_start": time(12, 0),
                        "break_end": time(13, 0),
                        "room": room,
                    },
                )

            patient_user = self._create_patient_user(clinic, slug)
            patient, _ = Patient.all_objects.get_or_create(
                clinic=clinic,
                cpf="",
                full_name="Paciente Demonstracao",
                defaults={
                    "email": patient_user.email,
                    "mobile": "11988887777",
                    "birth_date": date(1990, 5, 20),
                    "portal_user": patient_user,
                },
            )
            if not patient.portal_user_id:
                patient.portal_user = patient_user
                patient.save(update_fields=["portal_user"])

            self._seed_finance(clinic, patient, professional, service, admin_user)

    def _seed_finance(self, clinic, patient, professional, service, user) -> None:
        """Lancamentos financeiros de exemplo para o financeiro nao nascer vazio."""
        from apps.finance import services as finance_services
        from apps.finance.models import (
            FinancialCategory,
            PaymentMethod,
            ProfessionalCommissionRule,
            ReceivableAccount,
        )

        finance_services.provision_finance_defaults(clinic)
        income_category = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.INCOME
        ).first()
        expense_category = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.EXPENSE
        ).first()
        pix = PaymentMethod.objects.filter(kind=PaymentMethod.Kind.PIX).first()

        ProfessionalCommissionRule.all_objects.get_or_create(
            clinic=clinic, professional=professional, service=None,
            defaults={"percentage": 40},
        )

        receivable, created = ReceivableAccount.all_objects.get_or_create(
            clinic=clinic, patient=patient, appointment=None,
            description="Consulta de demonstracao",
            defaults={
                "professional": professional,
                "service": service,
                "category": income_category,
                "due_date": date.today(),
                "gross_amount": service.price,
            },
        )
        if created and pix:
            finance_services.register_receivable_payment(
                receivable, amount=receivable.net_amount, method=pix, user=user,
            )

        from apps.finance.models import PayableAccount

        PayableAccount.all_objects.get_or_create(
            clinic=clinic, supplier_name="Fornecedor Demonstracao",
            description="Material de escritorio",
            defaults={
                "category": expense_category,
                "issue_date": date.today(),
                "due_date": date.today() + timedelta(days=15),
                "amount": 250,
            },
        )

    def _seed_system_finance(self, clinics) -> None:
        """Fatura/pagamento de assinatura + despesa do sistema, para o
        financeiro do sistema (superadmin) nao nascer vazio."""
        from apps.billing.models import Invoice, Payment, SystemExpense

        for clinic in clinics:
            subscription = getattr(clinic, "subscription", None)
            if subscription is None:
                continue
            invoice, _created = Invoice.all_objects.get_or_create(
                subscription=subscription,
                number=f"DEMO-{clinic.pk.hex[:8].upper()}",
                defaults={
                    "reference_month": date.today().replace(day=1),
                    "amount": subscription.price,
                    "due_date": date.today() + timedelta(days=10),
                    "status": Invoice.Status.PAID,
                    "paid_at": timezone.now(),
                },
            )
            Payment.all_objects.get_or_create(
                invoice=invoice,
                defaults={"amount": invoice.amount, "method": Payment.Method.PIX},
            )

        SystemExpense.all_objects.get_or_create(
            description="Infraestrutura em nuvem (demo)",
            expense_date=date.today(),
            defaults={
                "category": SystemExpense.Category.INFRASTRUCTURE,
                "amount": 450,
                "is_recurring": True,
            },
        )

    def _create_membership(self, clinic, email, name, role) -> User:
        user, created = User.objects.get_or_create(
            email=email, defaults={"full_name": name, "role": role}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        ClinicMembership.all_objects.get_or_create(
            user=user, clinic=clinic, defaults={"role": role, "is_default": True}
        )
        return user

    def _create_patient_user(self, clinic, slug) -> User:
        email = f"paciente.{slug}@jjasystem.com.br"
        user, created = User.objects.get_or_create(
            email=email, defaults={"full_name": "Paciente Demonstracao", "role": Roles.PATIENT}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user
