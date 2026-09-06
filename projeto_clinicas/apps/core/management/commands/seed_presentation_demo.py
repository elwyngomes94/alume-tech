"""
Cria uma clinica de demonstracao "pronta para apresentar a clientes"
(nao usar em producao).

Diferente de ``seed_demo`` (fixture minima para desenvolvimento, 1
profissional por clinica), este comando gera UMA clinica rica, pensada
para uma demonstracao comercial ao vivo:

    - 2 administradores
    - 2 recepcionistas
    - 4 profissionais, cada um com uma especialidade diferente
    - 100 pacientes
    - agenda com atendimentos passados, futuros e de hoje (incluindo
      alguns ja com senha de chamada gerada, para mostrar a fila em
      funcionamento)
    - lancamentos financeiros de exemplo

Todos os usuarios criados usam a MESMA senha, simples de digitar durante
uma apresentacao: 123456.

Uso:
    python manage.py seed_presentation_demo
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import Roles
from apps.billing.models import Plan
from apps.clinics.models import Clinic, InsurancePlan, Room, Service, Specialty
from apps.clinics.modules import ClinicType, MODULE_CATALOG
from apps.core.tenancy import tenant_context
from apps.patients.models import Patient
from apps.platform_admin.services import provision_clinic
from apps.professionals.models import Professional
from apps.scheduling.models import Appointment, ScheduleTemplate
from apps.tenants.models import ClinicMembership

DEMO_PASSWORD = "123456"

CLINIC_DOCUMENT = "44.444.444/0001-44"
CLINIC_TRADE_NAME = "Clinica Vida Plena"

SPECIALTIES = [
    ("Cardiologia", "#dc3545", "Consulta Cardiologica", 45, 280),
    ("Pediatria", "#0dcaf0", "Consulta Pediatrica", 30, 200),
    ("Ortopedia", "#fd7e14", "Consulta Ortopedica", 40, 250),
    ("Ginecologia", "#d63384", "Consulta Ginecologica", 40, 260),
]

DOCTOR_NAMES = [
    "Dr. Marcelo Andrade",
    "Dra. Fernanda Lima",
    "Dr. Rodrigo Souza",
    "Dra. Camila Ribeiro",
]

FIRST_NAMES = [
    "Ana", "Bruno", "Carla", "Daniel", "Eduarda", "Felipe", "Gabriela", "Hugo",
    "Isabela", "Joao", "Karina", "Lucas", "Mariana", "Nicolas", "Otavio",
    "Patricia", "Rafael", "Sabrina", "Thiago", "Vanessa", "William", "Yasmin",
    "Beatriz", "Caio", "Debora", "Enzo", "Flavia", "Gustavo", "Helena", "Igor",
]
LAST_NAMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves",
    "Pereira", "Lima", "Gomes", "Costa", "Ribeiro", "Martins", "Carvalho",
    "Almeida", "Lopes", "Soares", "Fernandes", "Vieira", "Barbosa",
]


class Command(BaseCommand):
    help = (
        "Cria uma clinica de demonstracao completa (100 pacientes, 4 medicos "
        "com especialidades diferentes, 2 recepcionistas, 2 administradores) "
        "para apresentacao a clientes."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20260101)
        self.stdout.write("Criando clinica de demonstracao para apresentacao...")

        plan = self._create_plan()
        clinic = self._create_clinic(plan)
        self._populate_clinic(clinic)

        self.stdout.write(self.style.SUCCESS("Clinica de demonstracao criada com sucesso."))
        self.stdout.write(f"Clinica: {clinic.trade_name}")
        self.stdout.write(f"Senha de todos os usuarios: {DEMO_PASSWORD}")
        self.stdout.write(
            "Use estes dados apenas em ambiente de desenvolvimento/homologacao."
        )

    # ------------------------------------------------------------------
    def _create_plan(self) -> Plan:
        plan, _created = Plan.objects.get_or_create(
            name="Plano Apresentacao (demo)",
            defaults={
                "tier": Plan.Tier.ENTERPRISE,
                "monthly_price": 599,
                "yearly_price": 5990,
                "max_professionals": 50,
                "max_users": 100,
                "max_patients": 5000,
                "max_storage_mb": 51200,
                "supports_api": True,
                "modules": list(MODULE_CATALOG.keys()),
            },
        )
        return plan

    def _create_clinic(self, plan: Plan) -> Clinic:
        clinic, created = Clinic.all_objects.get_or_create(
            document=CLINIC_DOCUMENT,
            defaults={
                "legal_name": "Clinica Vida Plena Saude Ltda",
                "trade_name": CLINIC_TRADE_NAME,
                "clinic_type": ClinicType.MEDICAL,
                "city": "Sao Paulo",
                "state": "SP",
                "status": Clinic.Status.ACTIVE,
                "email": "contato@clinicavidaplena.com.br",
                "phone": "11988880000",
            },
        )
        if created:
            provision_clinic(clinic, plan=plan)
        clinic.modules = list(MODULE_CATALOG.keys())
        clinic.save(update_fields=["modules"])
        return clinic

    def _create_user(self, email, name, role) -> User:
        user, created = User.objects.get_or_create(
            email=email, defaults={"full_name": name, "role": role}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user

    def _create_membership(self, clinic, email, name, role) -> User:
        user = self._create_user(email, name, role)
        ClinicMembership.all_objects.get_or_create(
            user=user, clinic=clinic, defaults={"role": role, "is_default": True}
        )
        return user

    # ------------------------------------------------------------------
    def _populate_clinic(self, clinic: Clinic) -> None:
        with tenant_context(clinic):
            if Patient.objects.filter(clinic=clinic).exists():
                self.stdout.write(
                    "Clinica ja possui pacientes -- pulando geracao de pacientes/agenda "
                    "(rode novamente apos limpar os dados se quiser recriar do zero)."
                )
                return

            InsurancePlan.all_objects.get_or_create(clinic=clinic, name="Particular")
            InsurancePlan.all_objects.get_or_create(clinic=clinic, name="Unimed")

            rooms = [
                Room.all_objects.get_or_create(clinic=clinic, name=f"Sala {i}")[0]
                for i in range(1, 5)
            ]

            self._create_membership(
                clinic, "admin1@clinicavidaplena.com.br", "Ana Paula Martins", Roles.CLINIC_ADMIN
            )
            self._create_membership(
                clinic, "admin2@clinicavidaplena.com.br", "Carlos Eduardo Nunes", Roles.CLINIC_ADMIN
            )
            self._create_membership(
                clinic, "recepcao1@clinicavidaplena.com.br", "Juliana Rocha", Roles.RECEPTIONIST
            )
            self._create_membership(
                clinic, "recepcao2@clinicavidaplena.com.br", "Pedro Henrique Dias", Roles.RECEPTIONIST
            )

            professionals = []
            for index, (spec_name, color, service_name, duration, price) in enumerate(SPECIALTIES):
                specialty, _ = Specialty.all_objects.get_or_create(
                    clinic=clinic, name=spec_name, defaults={"color": color}
                )
                service, _ = Service.all_objects.get_or_create(
                    clinic=clinic, name=service_name,
                    defaults={
                        "specialty": specialty, "duration_minutes": duration, "price": price,
                        "requires_room": True,
                    },
                )
                doctor_name = DOCTOR_NAMES[index]
                slug = spec_name.lower()
                email = f"medico.{slug}@clinicavidaplena.com.br"
                professional_user = self._create_membership(clinic, email, doctor_name, Roles.PROFESSIONAL)
                professional, _ = Professional.all_objects.get_or_create(
                    clinic=clinic,
                    user=professional_user,
                    defaults={
                        "full_name": doctor_name,
                        "email": email,
                        "council": "CRM",
                        "registry_number": f"{100000 + index}",
                        "registry_state": clinic.state,
                    },
                )
                professional.specialties.add(specialty)
                professional.services.add(service)
                room = rooms[index % len(rooms)]
                professional.rooms.add(room)

                for weekday in range(5):  # segunda a sexta
                    ScheduleTemplate.all_objects.get_or_create(
                        clinic=clinic, professional=professional, weekday=weekday,
                        defaults={
                            "start_time": time(8, 0), "end_time": time(18, 0),
                            "slot_minutes": duration, "break_start": time(12, 0),
                            "break_end": time(13, 0), "room": room,
                        },
                    )
                professionals.append((professional, service, room))

            patients = self._create_patients(clinic, count=100)
            self._create_appointments(clinic, professionals, patients)
            self._seed_finance(clinic)

    def _create_patients(self, clinic: Clinic, *, count: int) -> list:
        patients = []
        for i in range(count):
            first = FIRST_NAMES[i % len(FIRST_NAMES)]
            last = f"{LAST_NAMES[(i * 3) % len(LAST_NAMES)]} {LAST_NAMES[(i * 7 + 2) % len(LAST_NAMES)]}"
            full_name = f"{first} {last}"
            age_years = random.randint(1, 90)
            birth_date = date.today() - timedelta(days=age_years * 365 + random.randint(0, 364))
            gender = Patient.Gender.FEMALE if i % 2 == 0 else Patient.Gender.MALE
            ddd = random.choice(["11", "21", "31", "41", "51"])
            mobile = f"{ddd}9{random.randint(10000000, 99999999)}"
            patient = Patient.objects.create(
                clinic=clinic, cpf="", full_name=full_name,
                gender=gender, birth_date=birth_date, mobile=mobile,
                email=f"paciente{i + 1}@exemplo.com.br",
            )
            patients.append(patient)
        return patients

    def _create_appointments(self, clinic: Clinic, professionals: list, patients: list) -> None:
        from apps.calling.services import create_ticket_for_checkin, register_call

        today = timezone.localdate()
        patient_pool = list(patients)
        random.shuffle(patient_pool)
        pool_index = 0

        def next_patient():
            nonlocal pool_index
            patient = patient_pool[pool_index % len(patient_pool)]
            pool_index += 1
            return patient

        def make_slot(day, hour, minute, duration):
            start = timezone.make_aware(datetime.combine(day, time(hour, minute)))
            return start, start + timedelta(minutes=duration)

        for professional, service, room in professionals:
            hours = [8, 9, 10, 11, 14, 15, 16, 17]

            # --- atendimentos passados (ultimos 12 dias uteis) ------------
            past_day = today - timedelta(days=1)
            created_past = 0
            while created_past < 8:
                if past_day.weekday() < 5:
                    hour = hours[created_past % len(hours)]
                    start, end = make_slot(past_day, hour, 0, service.duration_minutes)
                    status = Appointment.Status.COMPLETED
                    if created_past == 6:
                        status = Appointment.Status.NO_SHOW
                    elif created_past == 7:
                        status = Appointment.Status.CANCELED
                    appt = Appointment.objects.create(
                        patient=next_patient(), professional=professional, service=service,
                        room=room, start_at=start, end_at=end, status=status,
                    )
                    if status == Appointment.Status.COMPLETED:
                        appt.checked_in_at = start - timedelta(minutes=10)
                        appt.called_at = start - timedelta(minutes=5)
                        appt.started_at = start
                        appt.finished_at = end
                    elif status == Appointment.Status.CANCELED:
                        appt.canceled_at = start - timedelta(days=1)
                        appt.cancel_reason = "Paciente remarcou por telefone."
                    appt.save()
                    created_past += 1
                past_day -= timedelta(days=1)

            # --- atendimentos futuros (proximos 12 dias uteis) ------------
            future_day = today + timedelta(days=1)
            created_future = 0
            while created_future < 6:
                if future_day.weekday() < 5:
                    hour = hours[created_future % len(hours)]
                    start, end = make_slot(future_day, hour, 0, service.duration_minutes)
                    status = (
                        Appointment.Status.CONFIRMED if created_future % 2 == 0
                        else Appointment.Status.SCHEDULED
                    )
                    appt = Appointment.objects.create(
                        patient=next_patient(), professional=professional, service=service,
                        room=room, start_at=start, end_at=end, status=status,
                    )
                    if status == Appointment.Status.CONFIRMED:
                        appt.confirmed_at = timezone.now()
                        appt.save(update_fields=["confirmed_at"])
                    created_future += 1
                future_day += timedelta(days=1)

            # --- atendimentos de hoje (fila de chamada em funcionamento) --
            # Sempre criados, mesmo em fim de semana -- e a parte mais
            # importante da demonstracao ao vivo (fila de chamada) e nao
            # pode depender do dia em que a apresentacao acontece.
            start, end = make_slot(today, hours[0], 0, service.duration_minutes)
            checked_in = Appointment.objects.create(
                patient=next_patient(), professional=professional, service=service,
                room=room, start_at=start, end_at=end,
                status=Appointment.Status.CHECKED_IN, checked_in_at=timezone.now(),
            )
            create_ticket_for_checkin(checked_in)

            start2, end2 = make_slot(today, hours[1], 0, service.duration_minutes)
            called = Appointment.objects.create(
                patient=next_patient(), professional=professional, service=service,
                room=room, start_at=start2, end_at=end2,
                status=Appointment.Status.CALLED,
                checked_in_at=timezone.now() - timedelta(minutes=8),
                called_at=timezone.now(),
            )
            ticket = create_ticket_for_checkin(called)
            if ticket is not None:
                register_call(called)

    def _seed_finance(self, clinic: Clinic) -> None:
        """
        Contas a receber para os atendimentos concluidos -- sem isso o
        Financeiro nasce zerado, o que enfraquece a demonstracao (e um dos
        principais modulos do sistema).
        """
        from apps.finance import services as finance_services
        from apps.finance.models import FinancialCategory, PaymentMethod, ReceivableAccount

        finance_services.provision_finance_defaults(clinic)
        income_category = FinancialCategory.objects.filter(
            kind=FinancialCategory.Kind.INCOME
        ).first()
        pix = PaymentMethod.objects.filter(kind=PaymentMethod.Kind.PIX).first()

        completed = Appointment.objects.filter(
            clinic=clinic, status=Appointment.Status.COMPLETED,
        ).select_related("patient", "professional", "service")
        for position, appointment in enumerate(completed):
            receivable, created = ReceivableAccount.all_objects.get_or_create(
                clinic=clinic, appointment=appointment,
                defaults={
                    "patient": appointment.patient,
                    "professional": appointment.professional,
                    "service": appointment.service,
                    "category": income_category,
                    "description": f"{appointment.service} - {appointment.patient.display_name}",
                    "due_date": appointment.start_at.date(),
                    "gross_amount": appointment.service.price if appointment.service else 0,
                },
            )
            if created and pix and position % 4 != 0:
                # 3 em cada 4 atendimentos concluidos ja aparecem pagos --
                # o restante fica pendente/vencido, para o financeiro
                # mostrar os dois estados na demonstracao.
                finance_services.register_receivable_payment(
                    receivable, amount=receivable.net_amount, method=pix,
                )
