"""
Exportadores de relatorio: CSV, Excel e PDF.

CSV funciona sem dependencia externa. Excel usa ``openpyxl`` e PDF usa
``reportlab`` -- ambos opcionais: se a biblioteca nao estiver instalada, a
exportacao correspondente informa o motivo em vez de quebrar a aplicacao.
"""
from __future__ import annotations

import csv
import io
from typing import Iterable, List, Sequence

from django.http import HttpResponse


def export_csv(filename: str, headers: Sequence[str], rows: Iterable[Sequence]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    response.write("﻿")  # BOM para o Excel reconhecer acentuacao
    writer = csv.writer(response, delimiter=";")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


def export_xlsx(
    filename: str, headers: Sequence[str], rows: Iterable[Sequence], title: str = "Relatorio"
) -> HttpResponse:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return _missing_dependency("openpyxl", "Excel")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.append(list(headers))
    header_fill = PatternFill("solid", start_color="0B5ED7")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    for row in rows:
        sheet.append(list(row))
    for index, header in enumerate(headers, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = max(
            14, min(48, len(str(header)) + 6)
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def export_pdf(
    filename: str,
    headers: Sequence[str],
    rows: Iterable[Sequence],
    title: str = "Relatorio",
    subtitle: str = "",
) -> HttpResponse:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        return _missing_dependency("reportlab", "PDF")

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    elements: List = [Paragraph(title, styles["Title"])]
    if subtitle:
        elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 8))

    data = [list(headers)] + [[str(value) for value in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b5ed7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
            ]
        )
    )
    elements.append(table)
    document.build(elements)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


def _missing_dependency(package: str, label: str) -> HttpResponse:
    return HttpResponse(
        f"Exportacao em {label} indisponivel: a biblioteca '{package}' nao esta "
        f"instalada neste ambiente. Instale com 'pip install {package}'.",
        status=501,
        content_type="text/plain; charset=utf-8",
    )


def export(fmt: str, filename: str, headers, rows, title: str = "Relatorio", subtitle: str = ""):
    fmt = (fmt or "csv").lower()
    if fmt == "xlsx":
        return export_xlsx(filename, headers, rows, title)
    if fmt == "pdf":
        return export_pdf(filename, headers, rows, title, subtitle)
    return export_csv(filename, headers, rows)
