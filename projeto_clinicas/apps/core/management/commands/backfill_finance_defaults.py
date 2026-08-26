"""
Popula formas de pagamento e categorias financeiras padrao nas clinicas que
ja existiam antes do modulo financeiro (idempotente).

Uso:
    python manage.py backfill_finance_defaults
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.clinics.models import Clinic
from apps.core.tenancy import tenant_context
from apps.finance.services import provision_finance_defaults


class Command(BaseCommand):
    help = "Cria categorias/formas de pagamento financeiras padrao para clinicas existentes."

    def handle(self, *args, **options):
        total = 0
        for clinic in Clinic.objects.all():
            with tenant_context(clinic):
                provision_finance_defaults(clinic)
            total += 1
            self.stdout.write(f"  {clinic.trade_name}: ok")
        self.stdout.write(self.style.SUCCESS(f"Financeiro provisionado em {total} clinica(s)."))
