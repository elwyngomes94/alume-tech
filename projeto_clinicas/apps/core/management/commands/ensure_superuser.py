"""
Garante a existencia do superadministrador da plataforma a partir de
variaveis de ambiente -- idempotente (cria na primeira vez, atualiza senha
e permissoes nas vezes seguintes). Usado na inicializacao do servico em
hospedagens sem acesso a shell interativo (ex.: plano gratuito do Render).

Uso:
    DJANGO_SUPERUSER_EMAIL=... DJANGO_SUPERUSER_PASSWORD=... \\
        python manage.py ensure_superuser
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.accounts.permissions import Roles


class Command(BaseCommand):
    help = "Cria/atualiza o superadministrador a partir de DJANGO_SUPERUSER_EMAIL/PASSWORD."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        full_name = os.environ.get("DJANGO_SUPERUSER_FULL_NAME", "Administrador")
        if not email or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_EMAIL/DJANGO_SUPERUSER_PASSWORD nao definidos -- nada a fazer."
            )
            return

        user, created = User.objects.get_or_create(
            email=email, defaults={"full_name": full_name},
        )
        user.full_name = full_name
        user.role = Roles.SUPERADMIN
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        user.save()

        action = "criado" if created else "atualizado"
        self.stdout.write(self.style.SUCCESS(f"Superadministrador {action}: {email}"))
