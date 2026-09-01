"""Capacidade maxima diaria (item A) e condicao de corrida (item B)."""
from __future__ import annotations

import threading
from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.scheduling import services
from apps.scheduling.models import Appointment, ScheduleTemplate
from tests.factories import make_clinic, make_patient, make_professional_user


class DailyCapacityTests(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        self.user, self.professional = make_professional_user(self.clinic)
        self.patient = make_patient(self.clinic)
        with tenant_context(self.clinic):
            self.template = ScheduleTemplate.objects.create(
                professional=self.professional,
                weekday=timezone.localdate().weekday(),
                start_time=time(8, 0),
                end_time=time(17, 0),
                slot_minutes=30,
                max_appointments=3,
            )

    def test_geracao_de_horarios_para_no_limite_configurado(self):
        with tenant_context(self.clinic):
            slots = services.day_slots(self.professional, timezone.localdate())
        self.assertEqual(len(slots), 3)

    def test_backend_recusa_agendamento_alem_do_limite_mesmo_fora_da_lista_gerada(self):
        from datetime import datetime

        today = timezone.localdate()
        with tenant_context(self.clinic):
            for hour in (9, 10, 11):
                services.create_appointment(
                    clinic=self.clinic,
                    patient=self.patient,
                    professional=self.professional,
                    start_at=timezone.make_aware(datetime.combine(today, time(hour, 0))),
                )
            with self.assertRaises(ValidationError) as ctx:
                services.create_appointment(
                    clinic=self.clinic,
                    patient=self.patient,
                    professional=self.professional,
                    start_at=timezone.make_aware(datetime.combine(today, time(14, 0))),
                )
        self.assertIn("limite de 3", str(ctx.exception))

    def test_sem_limite_configurado_gera_todos_os_horarios(self):
        with tenant_context(self.clinic):
            self.template.max_appointments = None
            self.template.save()
            slots = services.day_slots(self.professional, timezone.localdate())
        # 08:00-17:00 a cada 30 min = 18 horarios, sem limite nenhum.
        self.assertEqual(len(slots), 18)


class RaceConditionTests(TransactionTestCase):
    """
    Confirma a garantia funcional (nunca dois agendamentos conflitantes
    gravados sob concorrencia). O mecanismo de trava que garante isso
    pode variar por banco (``select_for_update`` real no Postgres da
    producao; no SQLite dos testes o proprio banco ja serializa escritas
    no arquivo) -- o que este teste prova e o resultado, nao qual camada
    especifica impediu a corrida.
    """

    def setUp(self):
        self.clinic = make_clinic()
        self.user, self.professional = make_professional_user(self.clinic)
        with tenant_context(self.clinic):
            ScheduleTemplate.objects.create(
                professional=self.professional,
                weekday=timezone.localdate().weekday(),
                start_time=time(0, 0),
                end_time=time(23, 59),
                slot_minutes=30,
            )
        self.patient_1 = make_patient(self.clinic, full_name="Concorrente 1")
        self.patient_2 = make_patient(self.clinic, full_name="Concorrente 2")

    def test_duas_tentativas_simultaneas_no_mesmo_horario_so_uma_vence(self):
        start = (timezone.now() + timedelta(days=1)).replace(
            minute=0, second=0, microsecond=0
        )
        results = {}
        barrier = threading.Barrier(2)

        def attempt(key, patient):
            try:
                barrier.wait(timeout=5)
                with tenant_context(self.clinic):
                    services.create_appointment(
                        clinic=self.clinic,
                        patient=patient,
                        professional=self.professional,
                        start_at=start,
                    )
                results[key] = "ok"
            except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer rejeicao
                results[key] = f"error: {exc}"
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=attempt, args=("t1", self.patient_1)),
            threading.Thread(target=attempt, args=("t2", self.patient_2)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        outcomes = list(results.values())
        successes = [o for o in outcomes if o == "ok"]
        self.assertEqual(len(successes), 1, results)

        with tenant_context(self.clinic):
            count = Appointment.objects.filter(start_at=start).count()
        self.assertEqual(count, 1)
