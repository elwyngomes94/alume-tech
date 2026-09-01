"""Consultas dos relatorios da clinica (sempre restritas ao tenant ativo)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Dict, List, Tuple

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone


def _period_bounds(start: date, end: date):
    tz = timezone.get_current_timezone()
    from datetime import datetime, time

    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(end, time.max), tz),
    )


def patients_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.patients.models import Patient

    headers = ["Prontuario", "Nome", "Nascimento", "Telefone", "Convenio", "Status", "Cadastro"]
    rows = [
        [
            patient.record_number,
            patient.display_name,
            patient.birth_date.strftime("%d/%m/%Y") if patient.birth_date else "",
            patient.primary_phone,
            str(patient.insurance) if patient.insurance_id else "",
            patient.get_status_display(),
            timezone.localtime(patient.created_at).strftime("%d/%m/%Y"),
        ]
        for patient in Patient.objects.filter(
            created_at__date__gte=start, created_at__date__lte=end
        ).select_related("insurance").order_by("full_name")
    ]
    return headers, rows


def appointments_report(start: date, end: date, **filters) -> Tuple[List[str], List[List]]:
    from apps.scheduling.models import Appointment

    queryset = Appointment.objects.filter(
        start_at__date__gte=start, start_at__date__lte=end
    ).select_related("patient", "professional", "service")
    if filters.get("professional"):
        queryset = queryset.filter(professional_id=filters["professional"])
    if filters.get("status"):
        queryset = queryset.filter(status=filters["status"])

    headers = ["Data", "Hora", "Paciente", "Profissional", "Servico", "Status", "Origem"]
    rows = [
        [
            timezone.localtime(item.start_at).strftime("%d/%m/%Y"),
            timezone.localtime(item.start_at).strftime("%H:%M"),
            item.patient.display_name,
            item.professional.display_name,
            str(item.service) if item.service_id else "",
            item.get_status_display(),
            item.get_origin_display(),
        ]
        for item in queryset.order_by("start_at")
    ]
    return headers, rows


def production_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    """Producao por profissional no periodo."""
    from apps.scheduling.models import Appointment

    data = (
        Appointment.objects.filter(start_at__date__gte=start, start_at__date__lte=end)
        .values("professional__full_name")
        .annotate(
            total=Count("id"),
            concluidos=Count("id", filter=Q(status=Appointment.Status.COMPLETED)),
            cancelados=Count("id", filter=Q(status=Appointment.Status.CANCELED)),
            faltas=Count("id", filter=Q(status=Appointment.Status.NO_SHOW)),
        )
        .order_by("-total")
    )
    headers = ["Profissional", "Agendados", "Concluidos", "Cancelados", "Faltas", "Efetividade"]
    rows = []
    for item in data:
        total = item["total"] or 0
        efetividade = f"{(item['concluidos'] / total * 100):.1f}%" if total else "0%"
        rows.append(
            [
                item["professional__full_name"],
                total,
                item["concluidos"],
                item["cancelados"],
                item["faltas"],
                efetividade,
            ]
        )
    return headers, rows


def services_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.scheduling.models import Appointment

    data = (
        Appointment.objects.filter(start_at__date__gte=start, start_at__date__lte=end)
        .exclude(service__isnull=True)
        .values("service__name")
        .annotate(total=Count("id"), ticket=Avg("price"))
        .order_by("-total")
    )
    headers = ["Servico", "Quantidade", "Valor medio"]
    rows = [
        [item["service__name"], item["total"], f"R$ {item['ticket'] or 0:.2f}"] for item in data
    ]
    return headers, rows


def cancellations_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.scheduling.models import Appointment

    queryset = Appointment.objects.filter(
        start_at__date__gte=start,
        start_at__date__lte=end,
        status__in=[Appointment.Status.CANCELED, Appointment.Status.NO_SHOW],
    ).select_related("patient", "professional", "canceled_by")
    headers = ["Data", "Paciente", "Profissional", "Situacao", "Motivo", "Registrado por"]
    rows = [
        [
            timezone.localtime(item.start_at).strftime("%d/%m/%Y %H:%M"),
            item.patient.display_name,
            item.professional.display_name,
            item.get_status_display(),
            item.cancel_reason,
            item.canceled_by.full_name if item.canceled_by_id else "",
        ]
        for item in queryset.order_by("-start_at")
    ]
    return headers, rows


def attendances_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.medical_records.models import MedicalRecordEntry

    queryset = MedicalRecordEntry.objects.filter(
        attended_at__date__gte=start, attended_at__date__lte=end, is_draft=False
    ).select_related("record__patient", "professional", "template")
    headers = ["Data", "Paciente", "Profissional", "Modelo", "Assinado"]
    rows = [
        [
            timezone.localtime(entry.attended_at).strftime("%d/%m/%Y %H:%M"),
            entry.record.patient.display_name,
            entry.professional.display_name,
            entry.template.name if entry.template_id else "",
            "Sim" if entry.is_signed else "Nao",
        ]
        for entry in queryset.order_by("-attended_at")
    ]
    return headers, rows


def professionals_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.professionals.models import Professional

    headers = ["Nome", "Registro", "Especialidades", "Ativo", "Agendamentos no periodo"]
    rows = []
    for professional in Professional.objects.prefetch_related("specialties").order_by("full_name"):
        total = professional.appointments.filter(
            start_at__date__gte=start, start_at__date__lte=end
        ).count()
        rows.append(
            [
                professional.display_name,
                professional.registry_label,
                professional.specialty_names,
                "Sim" if professional.is_active else "Nao",
                total,
            ]
        )
    return headers, rows


def exams_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.examinations.models import ExaminationRequest

    queryset = ExaminationRequest.objects.filter(
        requested_at__date__gte=start, requested_at__date__lte=end
    ).select_related("patient", "professional").prefetch_related("items")
    headers = ["Numero", "Paciente", "Solicitante", "Exames", "Prioridade", "Status", "Data"]
    rows = [
        [
            item.number,
            item.patient.display_name,
            item.professional.display_name,
            ", ".join(exam.name for exam in item.items.all()),
            item.get_priority_display(),
            item.get_status_display(),
            timezone.localtime(item.requested_at).strftime("%d/%m/%Y"),
        ]
        for item in queryset.order_by("-requested_at")
    ]
    return headers, rows


def documents_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.documents.models import Document

    queryset = Document.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    ).select_related("patient", "category", "uploaded_by")
    headers = ["Titulo", "Paciente", "Categoria", "Tamanho", "Enviado por", "Data"]
    rows = [
        [
            doc.title,
            doc.patient.display_name if doc.patient_id else "-",
            str(doc.category) if doc.category_id else "-",
            doc.human_size,
            doc.uploaded_by.full_name if doc.uploaded_by_id else "-",
            timezone.localtime(doc.created_at).strftime("%d/%m/%Y %H:%M"),
        ]
        for doc in queryset.order_by("-created_at")
    ]
    return headers, rows


def users_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.tenants.models import ClinicMembership

    queryset = ClinicMembership.all_objects.filter(is_deleted=False).select_related("user")
    headers = ["Nome", "E-mail", "Perfil", "Cargo", "Ativo", "Vinculo desde"]
    rows = [
        [
            m.user.full_name,
            m.user.email,
            m.get_role_display(),
            m.job_title,
            "Sim" if m.is_active and m.user.is_active else "Nao",
            timezone.localtime(m.created_at).strftime("%d/%m/%Y"),
        ]
        for m in queryset.order_by("user__full_name")
    ]
    return headers, rows


def audit_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.audit.models import AuditLog

    queryset = AuditLog.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    headers = ["Data", "Usuario", "Acao", "Objeto", "Resultado"]
    rows = [
        [
            timezone.localtime(log.created_at).strftime("%d/%m/%Y %H:%M:%S"),
            log.user_email,
            log.action_label,
            log.object_repr or log.description,
            log.result,
        ]
        for log in queryset.order_by("-created_at")[:2000]
    ]
    return headers, rows


# ---------------------------------------------------------------------------
# Financeiro
# ---------------------------------------------------------------------------
def receivables_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import ReceivableAccount

    queryset = ReceivableAccount.objects.filter(
        due_date__gte=start, due_date__lte=end
    ).select_related("patient", "professional", "category")
    headers = ["Paciente", "Profissional", "Categoria", "Vencimento", "Valor", "Recebido",
               "Saldo", "Status"]
    rows = [
        [
            r.patient.display_name if r.patient_id else r.description,
            r.professional.display_name if r.professional_id else "-",
            str(r.category),
            r.due_date.strftime("%d/%m/%Y"),
            f"R$ {r.net_amount:.2f}",
            f"R$ {r.paid_amount:.2f}",
            f"R$ {r.balance:.2f}",
            r.get_status_display(),
        ]
        for r in queryset.order_by("due_date")
    ]
    return headers, rows


def payables_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import PayableAccount

    queryset = PayableAccount.objects.filter(
        due_date__gte=start, due_date__lte=end
    ).select_related("category", "cost_center")
    headers = ["Fornecedor", "Categoria", "Centro de custo", "Vencimento", "Valor", "Pago",
               "Saldo", "Status"]
    rows = [
        [
            p.supplier_name,
            str(p.category),
            str(p.cost_center) if p.cost_center_id else "-",
            p.due_date.strftime("%d/%m/%Y"),
            f"R$ {p.amount:.2f}",
            f"R$ {p.paid_amount:.2f}",
            f"R$ {p.balance:.2f}",
            p.get_status_display(),
        ]
        for p in queryset.order_by("due_date")
    ]
    return headers, rows


def overdue_accounts_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialStatus, PayableAccount, ReceivableAccount

    headers = ["Tipo", "Descricao", "Vencimento", "Saldo em aberto"]
    rows = []
    for r in ReceivableAccount.objects.filter(
        status__in=[FinancialStatus.PENDING, FinancialStatus.PARTIAL, FinancialStatus.OVERDUE],
        due_date__lt=timezone.localdate(),
    ).select_related("patient"):
        rows.append([
            "A receber",
            r.patient.display_name if r.patient_id else r.description,
            r.due_date.strftime("%d/%m/%Y"),
            f"R$ {r.balance:.2f}",
        ])
    for p in PayableAccount.objects.filter(
        status__in=[FinancialStatus.PENDING, FinancialStatus.PARTIAL, FinancialStatus.OVERDUE],
        due_date__lt=timezone.localdate(),
    ):
        rows.append([
            "A pagar",
            p.supplier_name,
            p.due_date.strftime("%d/%m/%Y"),
            f"R$ {p.balance:.2f}",
        ])
    return headers, sorted(rows, key=lambda row: row[2])


def cashflow_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.core.tenancy import get_current_tenant
    from apps.finance.services import cashflow_entries

    clinic = get_current_tenant()
    entries = cashflow_entries(clinic, start, end) if clinic else []
    headers = ["Data", "Tipo", "Descricao", "Forma de pagamento", "Valor", "Saldo"]
    rows = [
        [
            timezone.localtime(e.transaction.paid_at).strftime("%d/%m/%Y %H:%M"),
            e.transaction.get_kind_display(),
            e.transaction.notes or (str(e.transaction.category) if e.transaction.category_id else ""),
            e.transaction.method.name if e.transaction.method_id else "-",
            f"R$ {e.transaction.amount:.2f}",
            f"R$ {e.running_balance:.2f}",
        ]
        for e in entries
    ]
    return headers, rows


def financial_result_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.services import dashboard_summary
    from apps.core.tenancy import get_current_tenant

    clinic = get_current_tenant()
    summary = dashboard_summary(clinic, start, end) if clinic else {}
    headers = ["Indicador", "Valor"]
    rows = [
        ["Entradas do periodo", f"R$ {summary.get('period_income', 0):.2f}"],
        ["Saidas do periodo", f"R$ {summary.get('period_expense', 0):.2f}"],
        ["Resultado do periodo", f"R$ {summary.get('period_result', 0):.2f}"],
        ["Saldo atual", f"R$ {summary.get('current_balance', 0):.2f}"],
        ["Contas a receber em aberto", f"R$ {summary.get('receivables_open', 0):.2f}"],
        ["Contas a pagar em aberto", f"R$ {summary.get('payables_open', 0):.2f}"],
    ]
    return headers, rows


def revenue_by_professional_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialStatus, ReceivableAccount

    queryset = (
        ReceivableAccount.objects.filter(
            service_date__gte=start, service_date__lte=end, status=FinancialStatus.PAID,
            professional__isnull=False,
        )
        .values("professional__full_name")
        .annotate(
            total=Sum("gross_amount"), comissao=Sum("professional_commission_amount"),
        )
        .order_by("-total")
    )
    headers = ["Profissional", "Faturamento bruto", "Comissao"]
    rows = [
        [item["professional__full_name"], f"R$ {item['total'] or 0:.2f}",
         f"R$ {item['comissao'] or 0:.2f}"]
        for item in queryset
    ]
    return headers, rows


def revenue_by_service_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialStatus, ReceivableAccount

    queryset = (
        ReceivableAccount.objects.filter(
            service_date__gte=start, service_date__lte=end, status=FinancialStatus.PAID,
            service__isnull=False,
        )
        .values("service__name")
        .annotate(total=Sum("gross_amount"), quantidade=Count("id"))
        .order_by("-total")
    )
    headers = ["Servico/Procedimento", "Quantidade", "Faturamento"]
    rows = [
        [item["service__name"], item["quantidade"], f"R$ {item['total'] or 0:.2f}"]
        for item in queryset
    ]
    return headers, rows


def expenses_by_category_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialTransaction

    queryset = (
        FinancialTransaction.objects.filter(
            kind=FinancialTransaction.Kind.EXPENSE, paid_at__date__gte=start,
            paid_at__date__lte=end,
        )
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    headers = ["Categoria", "Total"]
    rows = [[item["category__name"] or "Sem categoria", f"R$ {item['total']:.2f}"]
            for item in queryset]
    return headers, rows


def expenses_by_costcenter_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialTransaction

    queryset = (
        FinancialTransaction.objects.filter(
            kind=FinancialTransaction.Kind.EXPENSE, paid_at__date__gte=start,
            paid_at__date__lte=end,
        )
        .values("cost_center__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    headers = ["Centro de custo", "Total"]
    rows = [[item["cost_center__name"] or "Sem centro de custo", f"R$ {item['total']:.2f}"]
            for item in queryset]
    return headers, rows


def commissions_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialStatus, ReceivableAccount

    queryset = ReceivableAccount.objects.filter(
        service_date__gte=start, service_date__lte=end, status=FinancialStatus.PAID,
        professional__isnull=False,
    ).select_related("professional", "service", "patient")
    headers = ["Profissional", "Paciente", "Servico", "Valor bruto", "Comissao", "Valor clinica"]
    rows = [
        [
            r.professional.display_name,
            r.patient.display_name if r.patient_id else r.description,
            str(r.service) if r.service_id else "-",
            f"R$ {r.net_amount:.2f}",
            f"R$ {(r.professional_commission_amount or 0):.2f}",
            f"R$ {(r.clinic_amount or 0):.2f}",
        ]
        for r in queryset.order_by("professional__full_name")
    ]
    return headers, rows


def delinquency_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialStatus, ReceivableAccount

    queryset = ReceivableAccount.objects.filter(
        status__in=[FinancialStatus.PENDING, FinancialStatus.PARTIAL, FinancialStatus.OVERDUE],
        due_date__lt=timezone.localdate(),
    ).select_related("patient")
    headers = ["Paciente", "Vencimento", "Dias em atraso", "Saldo devedor"]
    today = timezone.localdate()
    rows = [
        [
            r.patient.display_name if r.patient_id else r.description,
            r.due_date.strftime("%d/%m/%Y"),
            (today - r.due_date).days,
            f"R$ {r.balance:.2f}",
        ]
        for r in queryset.order_by("due_date")
    ]
    return headers, rows


def dre_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    """DRE simplificada: receitas por categoria - despesas por categoria = resultado."""
    from apps.finance.models import FinancialTransaction

    income_rows = (
        FinancialTransaction.objects.filter(
            kind=FinancialTransaction.Kind.INCOME, paid_at__date__gte=start,
            paid_at__date__lte=end,
        )
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    expense_rows = (
        FinancialTransaction.objects.filter(
            kind=FinancialTransaction.Kind.EXPENSE, paid_at__date__gte=start,
            paid_at__date__lte=end,
        )
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    total_income = sum((item["total"] for item in income_rows), Decimal("0"))
    total_expense = sum((item["total"] for item in expense_rows), Decimal("0"))

    headers = ["Grupo", "Categoria", "Valor"]
    rows = [["RECEITAS", item["category__name"] or "Sem categoria", f"R$ {item['total']:.2f}"]
            for item in income_rows]
    rows.append(["RECEITAS", "Total de receitas", f"R$ {total_income:.2f}"])
    rows += [["DESPESAS", item["category__name"] or "Sem categoria", f"R$ {item['total']:.2f}"]
             for item in expense_rows]
    rows.append(["DESPESAS", "Total de despesas", f"R$ {total_expense:.2f}"])
    rows.append(["RESULTADO", "Resultado do periodo", f"R$ {total_income - total_expense:.2f}"])
    return headers, rows


def payments_by_method_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialTransaction

    queryset = (
        FinancialTransaction.objects.filter(
            kind=FinancialTransaction.Kind.INCOME, paid_at__date__gte=start,
            paid_at__date__lte=end,
        )
        .values("method__name")
        .annotate(total=Sum("amount"), quantidade=Count("id"))
        .order_by("-total")
    )
    headers = ["Forma de pagamento", "Quantidade", "Total recebido"]
    rows = [
        [item["method__name"] or "-", item["quantidade"], f"R$ {item['total'] or 0:.2f}"]
        for item in queryset
    ]
    return headers, rows


def payments_by_receptionist_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialTransaction

    queryset = (
        FinancialTransaction.objects.filter(
            kind=FinancialTransaction.Kind.INCOME, paid_at__date__gte=start,
            paid_at__date__lte=end,
        )
        .values("created_by__full_name")
        .annotate(total=Sum("amount"), quantidade=Count("id"))
        .order_by("-total")
    )
    headers = ["Registrado por", "Quantidade de pagamentos", "Total recebido"]
    rows = [
        [item["created_by__full_name"] or "-", item["quantidade"], f"R$ {item['total'] or 0:.2f}"]
        for item in queryset
    ]
    return headers, rows


def partial_payments_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialStatus, ReceivableAccount

    queryset = ReceivableAccount.objects.filter(
        status=FinancialStatus.PARTIAL, service_date__gte=start, service_date__lte=end,
    ).select_related("patient", "professional")
    headers = ["Paciente", "Profissional", "Data", "Valor", "Recebido", "Saldo"]
    rows = [
        [
            r.patient.display_name if r.patient_id else r.description,
            r.professional.display_name if r.professional_id else "-",
            r.service_date.strftime("%d/%m/%Y"),
            f"R$ {r.net_amount:.2f}",
            f"R$ {r.paid_amount:.2f}",
            f"R$ {r.balance:.2f}",
        ]
        for r in queryset.order_by("service_date")
    ]
    return headers, rows


def refunds_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.finance.models import FinancialTransaction

    queryset = FinancialTransaction.objects.filter(
        kind=FinancialTransaction.Kind.REFUND, paid_at__date__gte=start, paid_at__date__lte=end,
    ).select_related("receivable__patient", "method", "created_by")
    headers = ["Data", "Paciente", "Valor estornado", "Forma", "Registrado por", "Motivo"]
    rows = [
        [
            timezone.localtime(t.paid_at).strftime("%d/%m/%Y %H:%M"),
            t.receivable.patient.display_name
            if t.receivable_id and t.receivable.patient_id else "-",
            f"R$ {t.amount:.2f}",
            t.method.name if t.method_id else "-",
            t.created_by.full_name if t.created_by_id else "-",
            t.notes,
        ]
        for t in queryset.order_by("-paid_at")
    ]
    return headers, rows


def stock_products_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    """Snapshot atual do estoque -- ignora o periodo (nao ha "estoque no passado")."""
    from apps.inventory.models import Product

    headers = ["Produto", "SKU", "Categoria", "Estoque atual", "Estoque minimo", "Status"]
    rows = [
        [
            product.name,
            product.sku or "-",
            product.category or "-",
            f"{product.current_stock} {product.unit}",
            f"{product.minimum_stock} {product.unit}",
            "Abaixo do minimo" if product.is_below_minimum else "OK",
        ]
        for product in Product.objects.all().order_by("name")
    ]
    return headers, rows


def stock_low_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    """Produtos com saldo abaixo do minimo -- tambem ignora o periodo."""
    from django.db.models import F

    from apps.inventory.models import Product

    headers = ["Produto", "SKU", "Estoque atual", "Estoque minimo", "Faltam"]
    rows = [
        [
            product.name,
            product.sku or "-",
            f"{product.current_stock} {product.unit}",
            f"{product.minimum_stock} {product.unit}",
            f"{product.minimum_stock - product.current_stock} {product.unit}",
        ]
        for product in Product.objects.filter(is_active=True, current_stock__lt=F("minimum_stock"))
        .order_by("name")
    ]
    return headers, rows


def occupancy_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    """
    Ocupacao da agenda por profissional/dia -- reaproveita a mesma conta
    usada no painel "Agenda inteligente" (``apps.scheduling.services.
    occupancy_for_day``), so que profissional por profissional em vez de
    somado, para bater com o formato do pedido (seção 23).
    """
    from datetime import timedelta as _timedelta

    from apps.professionals.models import Professional
    from apps.scheduling.services import occupancy_for_day

    professionals = list(Professional.objects.filter(is_active=True).order_by("full_name"))
    headers = [
        "Data", "Profissional", "Total de horarios", "Ocupados",
        "Disponiveis", "Bloqueados", "Taxa de ocupacao",
    ]
    rows = []
    day = start
    while day <= end:
        for professional in professionals:
            occupancy = occupancy_for_day(day, [professional])
            if occupancy["total"] == 0:
                continue
            rows.append(
                [
                    day.strftime("%d/%m/%Y"),
                    professional.display_name,
                    occupancy["total"],
                    occupancy["booked"],
                    occupancy["available"],
                    occupancy["blocked"],
                    f"{occupancy['occupancy_percent']}%",
                ]
            )
        day += _timedelta(days=1)
    return headers, rows


def stock_movements_report(start: date, end: date) -> Tuple[List[str], List[List]]:
    from apps.inventory.models import StockMovement

    queryset = StockMovement.objects.filter(
        moved_at__date__gte=start, moved_at__date__lte=end
    ).select_related("product", "created_by")
    headers = ["Data", "Produto", "Tipo", "Quantidade", "Motivo", "Registrado por"]
    rows = [
        [
            timezone.localtime(movement.moved_at).strftime("%d/%m/%Y %H:%M"),
            movement.product.name,
            movement.get_kind_display(),
            f"{movement.quantity} {movement.product.unit}",
            movement.reason or "-",
            movement.created_by.full_name if movement.created_by_id else "-",
        ]
        for movement in queryset.order_by("-moved_at")
    ]
    return headers, rows


#: Relatorios financeiros exigem a permissao 'finance.report.view' alem de
#: 'report.view'/'report.export' -- ver apps.reports.views.
FINANCE_REPORT_KEYS = {
    "contas_receber", "contas_pagar", "contas_vencidas", "fluxo_caixa",
    "resultado_financeiro", "faturamento_profissional", "faturamento_procedimento",
    "despesas_categoria", "despesas_centro_custo", "comissoes_profissionais",
    "inadimplencia", "dre_simplificada", "pagamentos_forma", "pagamentos_recepcionista",
    "pagamentos_parciais", "estornos",
}

REPORTS = {
    "pacientes": ("Pacientes", patients_report),
    "agendamentos": ("Agendamentos", appointments_report),
    "atendimentos": ("Atendimentos realizados", attendances_report),
    "producao": ("Producao por profissional", production_report),
    "servicos": ("Servicos mais utilizados", services_report),
    "cancelamentos": ("Cancelamentos e faltas", cancellations_report),
    "profissionais": ("Profissionais", professionals_report),
    "exames": ("Exames", exams_report),
    "documentos": ("Documentos", documents_report),
    "usuarios": ("Usuarios da clinica", users_report),
    "auditoria": ("Auditoria", audit_report),
    "contas_receber": ("Contas a receber", receivables_report),
    "contas_pagar": ("Contas a pagar", payables_report),
    "contas_vencidas": ("Contas vencidas", overdue_accounts_report),
    "fluxo_caixa": ("Fluxo de caixa", cashflow_report),
    "resultado_financeiro": ("Resultado financeiro", financial_result_report),
    "faturamento_profissional": ("Faturamento por profissional", revenue_by_professional_report),
    "faturamento_procedimento": ("Faturamento por procedimento", revenue_by_service_report),
    "despesas_categoria": ("Despesas por categoria", expenses_by_category_report),
    "despesas_centro_custo": ("Despesas por centro de custo", expenses_by_costcenter_report),
    "comissoes_profissionais": ("Comissoes dos profissionais", commissions_report),
    "inadimplencia": ("Inadimplencia", delinquency_report),
    "dre_simplificada": ("DRE simplificada", dre_report),
    "pagamentos_forma": ("Pagamentos por forma", payments_by_method_report),
    "pagamentos_recepcionista": ("Pagamentos por recepcionista", payments_by_receptionist_report),
    "pagamentos_parciais": ("Pagamentos parciais", partial_payments_report),
    "estornos": ("Estornos", refunds_report),
    "ocupacao_agenda": ("Ocupacao da agenda", occupancy_report),
    "estoque_produtos": ("Estoque - produtos", stock_products_report),
    "estoque_baixo": ("Estoque - abaixo do minimo", stock_low_report),
    "estoque_movimentacoes": ("Estoque - movimentacoes", stock_movements_report),
}


def indicators(start: date, end: date) -> Dict:
    """Indicadores agregados usados nos graficos do painel de relatorios."""
    from apps.patients.models import Patient
    from apps.scheduling.models import Appointment

    appointments = Appointment.objects.filter(start_at__date__gte=start, start_at__date__lte=end)
    by_day = (
        appointments.annotate(day=TruncDate("start_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    by_status = appointments.values("status").annotate(total=Count("id"))
    new_patients = (
        Patient.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )
    status_labels = dict(Appointment.Status.choices)
    return {
        "total_appointments": appointments.count(),
        "completed": appointments.filter(status=Appointment.Status.COMPLETED).count(),
        "canceled": appointments.filter(status=Appointment.Status.CANCELED).count(),
        "no_show": appointments.filter(status=Appointment.Status.NO_SHOW).count(),
        "new_patients": Patient.objects.filter(
            created_at__date__gte=start, created_at__date__lte=end
        ).count(),
        "chart_days": [item["day"].strftime("%d/%m") for item in by_day],
        "chart_day_values": [item["total"] for item in by_day],
        "chart_status_labels": [status_labels.get(item["status"], item["status"])
                                for item in by_status],
        "chart_status_values": [item["total"] for item in by_status],
        "chart_month_labels": [item["month"].strftime("%m/%Y") for item in new_patients],
        "chart_month_values": [item["total"] for item in new_patients],
    }
