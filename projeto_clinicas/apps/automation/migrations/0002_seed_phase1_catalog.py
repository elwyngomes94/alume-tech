"""Popula o catalogo das 3 automacoes da Fase 1 (idempotente)."""
from __future__ import annotations

from django.db import migrations

PHASE1_AUTOMATIONS = [
    (
        "waiting_list_invite", "Convite automatico da lista de espera", "operational",
        "Avisa a recepcao quando um agendamento cancelado libera um horario compativel "
        "com alguem aguardando na lista de espera.",
    ),
    (
        "financial_webhook_payment", "Baixa automatica via webhook financeiro", "operational",
        "Registra automaticamente o pagamento de uma conta a receber quando confirmado "
        "por uma integracao financeira externa.",
    ),
    (
        "payment_receipt", "Comprovante de pagamento automatico", "operational",
        "Gera e anexa automaticamente o comprovante em PDF de todo pagamento confirmado.",
    ),
]


def seed_catalog(apps, schema_editor):
    Automation = apps.get_model("automation", "Automation")
    for codename, name, layer, description in PHASE1_AUTOMATIONS:
        Automation.objects.get_or_create(
            codename=codename, defaults={"name": name, "layer": layer, "description": description},
        )


def remove_catalog(apps, schema_editor):
    Automation = apps.get_model("automation", "Automation")
    Automation.objects.filter(
        codename__in=[item[0] for item in PHASE1_AUTOMATIONS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("automation", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_catalog, remove_catalog),
    ]
