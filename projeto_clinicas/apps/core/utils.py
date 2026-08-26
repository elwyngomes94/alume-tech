"""Funcoes utilitarias compartilhadas."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from django.utils import timezone


def calculate_age(birth_date: Optional[date], reference: Optional[date] = None) -> Optional[int]:
    if not birth_date:
        return None
    reference = reference or timezone.localdate()
    return (
        reference.year
        - birth_date.year
        - ((reference.month, reference.day) < (birth_date.month, birth_date.day))
    )


def parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def period_range(period: str = "30d", start: str = "", end: str = "") -> Tuple[date, date]:
    """
    Converte um filtro de periodo em (inicio, fim).

    Aceita ``7d``, ``30d``, ``90d``, ``12m``, ``today``, ``month`` ou datas
    explicitas de inicio/fim.
    """
    today = timezone.localdate()
    start_date = parse_date(start)
    end_date = parse_date(end)
    if start_date and end_date:
        return start_date, end_date

    mapping = {
        "today": (today, today),
        "7d": (today - timedelta(days=6), today),
        "30d": (today - timedelta(days=29), today),
        "90d": (today - timedelta(days=89), today),
        "12m": (today - timedelta(days=364), today),
        "month": (today.replace(day=1), today),
    }
    return mapping.get(period, mapping["30d"])


def mask_document(value: str) -> str:
    """Mascara CPF/CNPJ para exibicao (LGPD: minimizacao em telas e listagens)."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11:
        return f"***.{digits[3:6]}.{digits[6:9]}-**"
    if len(digits) == 14:
        return f"**.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-**"
    return value or ""


def format_document(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return value or ""


def humanize_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def month_series(start: date, end: date):
    """Lista de tuplas (ano, mes) entre duas datas, inclusive."""
    current = start.replace(day=1)
    series = []
    while current <= end:
        series.append((current.year, current.month))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return series
