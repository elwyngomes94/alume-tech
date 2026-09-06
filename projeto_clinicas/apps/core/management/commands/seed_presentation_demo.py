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
from decimal import Decimal

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

#: Conteudo clinico de exemplo por especialidade, para o prontuario dos
#: pacientes com atendimento concluido nao nascer vazio na demonstracao.
#: Cada tupla preenche os campos do modelo "Consulta medica" padrao
#: (ver apps.medical_records.templates_catalog.MEDICAL_CONSULTATION).
CLINICAL_NOTES = {
    "Cardiologia": [
        {
            "queixa_principal": "Dor toracica ao esforco, ha cerca de 1 semana.",
            "historia_doenca_atual": "Paciente relata dor em aperto retroesternal durante "
                "atividade fisica moderada, sem irradiacao, aliviada com repouso.",
            "hipoteses_diagnosticas": "Angina estavel a esclarecer.",
            "diagnostico": "Dor toracica de esforco - investigacao em andamento.",
            "conduta": "Solicitado ECG de repouso e teste ergometrico. Orientado retorno "
                "com os exames em 15 dias e reforcada a importancia de repouso caso a dor "
                "recorra.",
            "exames_solicitados": "ECG, teste ergometrico, perfil lipidico.",
        },
        {
            "queixa_principal": "Palpitacoes ocasionais nas ultimas duas semanas.",
            "historia_doenca_atual": "Refere episodios de palpitacao de curta duracao, sem "
                "sincope, sem relacao clara com esforco.",
            "hipoteses_diagnosticas": "Extrassistolia benigna a confirmar.",
            "diagnostico": "Palpitacoes de provavel origem benigna.",
            "conduta": "Solicitado Holter de 24h. Orientado reduzir consumo de cafeina e "
                "retornar com o resultado.",
            "exames_solicitados": "Holter 24h, eletrolitos.",
        },
        {
            "queixa_principal": "Consulta de rotina para acompanhamento de hipertensao.",
            "historia_doenca_atual": "Paciente em uso regular da medicacao, refere boa "
                "adesao e nega efeitos colaterais.",
            "diagnostico": "Hipertensao arterial sistemica controlada.",
            "conduta": "Mantida a medicacao em uso. Reforcadas orientacoes sobre dieta "
                "hipossodica e atividade fisica regular. Retorno em 3 meses.",
            "retorno": "3 meses",
        },
    ],
    "Pediatria": [
        {
            "queixa_principal": "Febre e coriza ha 2 dias.",
            "historia_doenca_atual": "Mae relata febre de ate 38.5C, coriza clara e tosse "
                "leve, sem dificuldade respiratoria, aceitando bem liquidos.",
            "diagnostico": "Infeccao de vias aereas superiores.",
            "conduta": "Orientadas medidas de suporte (hidratacao, antitermico se febre), "
                "sinais de alarme explicados aos pais. Retorno se piora ou febre persistente "
                "por mais de 3 dias.",
        },
        {
            "queixa_principal": "Consulta de puericultura de rotina.",
            "historia_doenca_atual": "Crianca assintomatica, desenvolvimento neuropsicomotor "
                "adequado para a idade segundo relato dos pais.",
            "exame_fisico": "Bom estado geral, corado, hidratado, ausculta cardiopulmonar "
                "sem alteracoes.",
            "diagnostico": "Crescimento e desenvolvimento adequados para a idade.",
            "conduta": "Atualizada caderneta de vacinacao. Orientacoes gerais de "
                "alimentacao e sono. Proxima consulta de rotina em 6 meses.",
            "retorno": "6 meses",
        },
        {
            "queixa_principal": "Dor abdominal e falta de apetite ha 3 dias.",
            "historia_doenca_atual": "Sem febre associada, evacuacoes normais, sem vomitos.",
            "diagnostico": "Dor abdominal inespecifica, provavel origem funcional.",
            "conduta": "Orientada dieta leve e observacao. Retorno caso dor persista ou "
                "surjam novos sintomas.",
        },
    ],
    "Ortopedia": [
        {
            "queixa_principal": "Dor lombar apos esforco fisico.",
            "historia_doenca_atual": "Dor iniciada apos levantar peso, sem irradiacao para "
                "membros inferiores, piora ao movimento.",
            "exame_fisico": "Contratura de musculatura paravertebral lombar, sem sinais de "
                "comprometimento neurologico.",
            "diagnostico": "Lombalgia mecanica aguda.",
            "conduta": "Prescrito anti-inflamatorio e relaxante muscular, orientado repouso "
                "relativo e fisioterapia. Retorno em 2 semanas se persistir.",
            "prescricao": "Anti-inflamatorio via oral por 5 dias, relaxante muscular a noite.",
        },
        {
            "queixa_principal": "Dor no joelho direito ao caminhar, ha 1 mes.",
            "historia_doenca_atual": "Dor progressiva, pior ao subir escadas, sem historico "
                "de trauma recente.",
            "hipoteses_diagnosticas": "Condropatia patelar a confirmar.",
            "conduta": "Solicitada radiografia de joelho em duas incidencias. Encaminhado "
                "para fisioterapia. Retorno com o exame.",
            "exames_solicitados": "Radiografia de joelho direito.",
        },
        {
            "queixa_principal": "Acompanhamento pos-operatorio de fratura de punho.",
            "exame_fisico": "Boa consolidacao ao exame, mobilidade em recuperacao "
                "progressiva.",
            "diagnostico": "Evolucao pos-operatoria satisfatoria.",
            "conduta": "Mantida fisioterapia motora. Retorno em 30 dias para reavaliacao.",
            "retorno": "30 dias",
        },
    ],
    "Ginecologia": [
        {
            "queixa_principal": "Consulta de rotina - exame preventivo.",
            "historia_doenca_atual": "Paciente assintomatica, ciclos regulares, sem "
                "queixas no momento.",
            "conduta": "Realizada coleta de preventivo. Orientacoes sobre metodo "
                "contraceptivo em uso. Retorno com resultado em 30 dias.",
            "exames_solicitados": "Colpocitologia oncotica.",
            "retorno": "30 dias",
        },
        {
            "queixa_principal": "Irregularidade menstrual nos ultimos 2 ciclos.",
            "historia_doenca_atual": "Relata atraso e fluxo mais intenso que o habitual, "
                "nega dor importante.",
            "hipoteses_diagnosticas": "Disfuncao hormonal a esclarecer.",
            "conduta": "Solicitados exames hormonais e ultrassonografia transvaginal. "
                "Retorno com resultados.",
            "exames_solicitados": "Perfil hormonal, ultrassonografia transvaginal.",
        },
        {
            "queixa_principal": "Acompanhamento pre-natal de rotina.",
            "exame_fisico": "Altura uterina compativel com idade gestacional, bcf presente.",
            "diagnostico": "Gestacao de evolucao normal.",
            "conduta": "Mantido acompanhamento pre-natal. Solicitados exames de rotina do "
                "trimestre. Retorno em 4 semanas.",
            "retorno": "4 semanas",
        },
    ],
}

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
            self._seed_medical_records(clinic)

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

        # Pediatria so atende criancas -- separa a lista de pacientes por
        # idade para o prontuario nao misturar "consulta de puericultura"
        # com um paciente de 70 anos.
        children = [p for p in patients if p.birth_date and (today - p.birth_date).days < 13 * 365]
        adults = [p for p in patients if p not in children]
        random.shuffle(children)
        random.shuffle(adults)

        def make_pool(specialty_name):
            pool = list(children) if specialty_name == "Pediatria" and children else list(adults)
            return pool or list(patients)

        def make_slot(day, hour, minute, duration):
            start = timezone.make_aware(datetime.combine(day, time(hour, minute)))
            return start, start + timedelta(minutes=duration)

        for professional, service, room in professionals:
            specialty = professional.specialties.first()
            pool = make_pool(specialty.name if specialty else "")
            pool_index = 0

            def next_patient():
                nonlocal pool_index
                patient = pool[pool_index % len(pool)]
                pool_index += 1
                return patient

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

    def _seed_medical_records(self, clinic: Clinic) -> None:
        """
        Evolucao assinada para cada atendimento concluido, com conteudo
        clinico condizente com a especialidade -- e o que voce ve ao abrir
        o prontuario de um paciente durante a demonstracao.
        """
        from apps.medical_records.models import MedicalRecordEntry, RecordTemplate, VitalSigns
        from apps.medical_records.services import get_or_create_record

        template = RecordTemplate.objects.filter(is_default=True).first()
        completed = Appointment.objects.filter(
            clinic=clinic, status=Appointment.Status.COMPLETED,
        ).exclude(record_entries__isnull=False).select_related(
            "patient", "professional", "service"
        )
        for index, appointment in enumerate(completed):
            specialty = appointment.professional.specialties.first()
            bank = CLINICAL_NOTES.get(specialty.name if specialty else "", [])
            if not bank:
                continue
            content = dict(bank[index % len(bank)])
            content.setdefault("cid", "")

            record = get_or_create_record(appointment.patient)
            entry = MedicalRecordEntry.objects.create(
                record=record, appointment=appointment, professional=appointment.professional,
                template=template, title=str(appointment.service) if appointment.service else "Consulta",
                data=content, attended_at=appointment.start_at, is_draft=True,
            )
            entry.is_draft = False
            entry.signed_at = appointment.finished_at or appointment.start_at
            entry.signed_by = appointment.professional.user
            entry.signature_hash = entry.compute_signature()
            entry.save(
                update_fields=["is_draft", "signed_at", "signed_by", "signature_hash", "updated_at"]
            )

            age_years = (
                (appointment.start_at.date() - appointment.patient.birth_date).days // 365
                if appointment.patient.birth_date else 30
            )
            is_child = age_years < 13
            VitalSigns.objects.create(
                entry=entry,
                systolic_pressure=random.randint(90, 100) if is_child else random.randint(110, 135),
                diastolic_pressure=random.randint(55, 65) if is_child else random.randint(70, 88),
                heart_rate=random.randint(85, 110) if is_child else random.randint(62, 84),
                temperature=Decimal(str(round(random.uniform(36.2, 37.3), 1))),
                weight_kg=Decimal(str(round(random.uniform(9, 35), 1))) if is_child
                else Decimal(str(round(random.uniform(55, 95), 1))),
                height_cm=random.randint(70, 150) if is_child else random.randint(150, 190),
            )
