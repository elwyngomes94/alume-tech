#!/usr/bin/env python
"""Utilitario de linha de comando do JJA System."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - ambiente sem Django
        raise ImportError(
            "Nao foi possivel importar o Django. Verifique se ele esta instalado "
            "e disponivel na variavel de ambiente PYTHONPATH. Voce ativou o "
            "ambiente virtual?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
