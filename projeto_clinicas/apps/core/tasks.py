"""Tarefas de plataforma: backup e manutencao."""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("jja.security")


@shared_task(name="apps.core.tasks.executar_backup")
def executar_backup() -> str:
    """
    Rotina de backup do banco e dos arquivos privados.

    O destino (``BACKUP_ROOT``) deve ser um volume com acesso restrito e,
    idealmente, replicado para armazenamento externo criptografado. Backups
    NUNCA sao expostos a usuarios das clinicas.
    """
    backup_root = Path(settings.BACKUP_ROOT)
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    destination = backup_root / stamp
    destination.mkdir(parents=True, exist_ok=True)

    database = settings.DATABASES["default"]
    engine = database.get("ENGINE", "")

    try:
        if "postgresql" in engine:
            dump_file = destination / "database.dump"
            command = [
                "pg_dump",
                "--format=custom",
                f"--dbname=postgresql://{database.get('USER')}:{database.get('PASSWORD')}"
                f"@{database.get('HOST')}:{database.get('PORT') or 5432}/{database.get('NAME')}",
                f"--file={dump_file}",
            ]
            subprocess.run(command, check=True, capture_output=True)
        else:  # sqlite (desenvolvimento)
            source = Path(database["NAME"])
            if source.exists():
                shutil.copy2(source, destination / source.name)

        private_root = Path(settings.PRIVATE_MEDIA_ROOT)
        if private_root.exists():
            shutil.make_archive(str(destination / "private_media"), "zip", str(private_root))

        expurgar_backups_antigos()
        logger.info("backup-concluido destino=%s", destination)
        return str(destination)
    except Exception as exc:  # pragma: no cover - depende do ambiente
        logger.exception("Falha no backup: %s", exc)
        raise


def expurgar_backups_antigos() -> int:
    """Remove backups fora da janela de retencao configurada."""
    backup_root = Path(settings.BACKUP_ROOT)
    if not backup_root.exists():
        return 0
    limit = timezone.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    removed = 0
    for item in backup_root.iterdir():
        if not item.is_dir():
            continue
        modified = timezone.datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        if modified < limit:
            shutil.rmtree(item, ignore_errors=True)
            removed += 1
    return removed
