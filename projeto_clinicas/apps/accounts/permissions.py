"""
Catalogo de permissoes granulares do JJA System (RBAC).

As permissoes sao strings no formato ``dominio.acao`` e sao sempre avaliadas
**dentro do contexto de uma clinica**. Ter a permissao ``patient.view`` na
Clinica A nao concede nenhum direito na Clinica B.

Perfis padrao podem ser sobrescritos por papeis personalizados
(``accounts.Role``), permitindo que cada clinica ajuste o que cada perfil faz.
"""
from __future__ import annotations

from typing import Dict, List, Set


class Roles:
    """Perfis base do sistema."""

    SUPERADMIN = "superadmin"
    CLINIC_ADMIN = "clinic_admin"
    RECEPTIONIST = "receptionist"
    PROFESSIONAL = "professional"
    PATIENT = "patient"

    CHOICES = [
        (SUPERADMIN, "Superadministrador da plataforma"),
        (CLINIC_ADMIN, "Administrador da clinica"),
        (RECEPTIONIST, "Recepcionista"),
        (PROFESSIONAL, "Profissional"),
        (PATIENT, "Paciente"),
    ]

    #: Perfis que podem operar o painel da clinica (/app/)
    CLINIC_ROLES = (CLINIC_ADMIN, RECEPTIONIST, PROFESSIONAL)


#: (codename, descricao, grupo)
PERMISSION_CATALOG: List[tuple] = [
    # Clinica
    ("clinic.view", "Visualizar dados da clinica", "Clinica"),
    ("clinic.change", "Editar dados da clinica", "Clinica"),
    ("clinic.settings", "Alterar configuracoes da clinica", "Clinica"),
    # Usuarios e permissoes
    ("user.view", "Visualizar usuarios", "Usuarios"),
    ("user.add", "Cadastrar usuarios", "Usuarios"),
    ("user.change", "Editar usuarios", "Usuarios"),
    ("user.delete", "Desativar usuarios", "Usuarios"),
    ("role.manage", "Gerenciar papeis e permissoes", "Usuarios"),
    # Profissionais
    ("professional.view", "Visualizar profissionais", "Profissionais"),
    ("professional.add", "Cadastrar profissionais", "Profissionais"),
    ("professional.change", "Editar profissionais", "Profissionais"),
    ("professional.delete", "Excluir profissionais", "Profissionais"),
    # Pacientes
    ("patient.view", "Visualizar pacientes", "Pacientes"),
    ("patient.view_sensitive", "Visualizar dados sensiveis do paciente", "Pacientes"),
    ("patient.add", "Cadastrar pacientes", "Pacientes"),
    ("patient.change", "Editar pacientes", "Pacientes"),
    ("patient.delete", "Excluir pacientes", "Pacientes"),
    # Agenda
    ("appointment.view", "Visualizar agenda", "Agenda"),
    ("appointment.view_all", "Visualizar agenda de todos os profissionais", "Agenda"),
    ("appointment.add", "Criar agendamentos", "Agenda"),
    ("appointment.change", "Alterar agendamentos", "Agenda"),
    ("appointment.cancel", "Cancelar agendamentos", "Agenda"),
    ("appointment.payment", "Definir valor/pagamento no agendamento e dar baixa", "Agenda"),
    ("schedule.manage", "Configurar disponibilidade e bloqueios", "Agenda"),
    # Cadastros auxiliares
    ("service.manage", "Gerenciar servicos", "Cadastros"),
    ("specialty.manage", "Gerenciar especialidades", "Cadastros"),
    ("room.manage", "Gerenciar salas", "Cadastros"),
    ("insurance.manage", "Gerenciar convenios", "Cadastros"),
    # Prontuario
    ("medicalrecord.view", "Visualizar prontuarios", "Prontuario"),
    ("medicalrecord.add", "Registrar atendimento no prontuario", "Prontuario"),
    ("medicalrecord.change", "Editar registro nao assinado", "Prontuario"),
    ("medicalrecord.sign", "Assinar/finalizar registro", "Prontuario"),
    ("prescription.add", "Emitir prescricoes", "Prontuario"),
    ("template.manage", "Gerenciar modelos de prontuario", "Prontuario"),
    # Exames
    ("examination.view", "Visualizar exames", "Exames"),
    ("examination.request", "Solicitar exames", "Exames"),
    ("examination.result", "Registrar resultado de exame", "Exames"),
    # Documentos
    ("document.view", "Visualizar documentos", "Documentos"),
    ("document.add", "Enviar documentos", "Documentos"),
    ("document.download", "Baixar documentos", "Documentos"),
    ("document.delete", "Excluir documentos", "Documentos"),
    # Relatorios e auditoria
    ("report.view", "Visualizar relatorios", "Relatorios"),
    ("report.export", "Exportar relatorios", "Relatorios"),
    ("audit.view", "Consultar auditoria da clinica", "Seguranca"),
    ("lgpd.manage", "Gerenciar solicitacoes e consentimentos LGPD", "Seguranca"),
    # Faturamento
    ("billing.view", "Visualizar plano e faturas", "Faturamento"),
    # Financeiro da clinica
    ("finance.view", "Visualizar financeiro", "Financeiro"),
    ("finance.add", "Criar lancamento financeiro", "Financeiro"),
    ("finance.change", "Editar lancamento financeiro", "Financeiro"),
    ("finance.cancel", "Cancelar lancamento financeiro", "Financeiro"),
    ("finance.cashflow.view", "Visualizar fluxo de caixa", "Financeiro"),
    (
        "finance.category.manage",
        "Gerenciar categorias, centros de custo e formas de pagamento",
        "Financeiro",
    ),
    ("finance.commission.view", "Visualizar comissao de profissionais", "Financeiro"),
    ("finance.report.view", "Visualizar/exportar relatorios financeiros", "Financeiro"),
    # Automacao
    ("automation.view", "Visualizar configuracoes e historico de automacoes", "Automacao"),
    ("automation.manage", "Ativar/desativar automacoes e gerenciar o webhook", "Automacao"),
]

ALL_PERMISSIONS: Set[str] = {codename for codename, _label, _group in PERMISSION_CATALOG}

PERMISSION_LABELS: Dict[str, str] = {c: label for c, label, _g in PERMISSION_CATALOG}


def permissions_by_group() -> Dict[str, List[tuple]]:
    grouped: Dict[str, List[tuple]] = {}
    for codename, label, group in PERMISSION_CATALOG:
        grouped.setdefault(group, []).append((codename, label))
    return grouped


#: Permissoes concedidas por perfil quando nao ha papel personalizado.
DEFAULT_ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    Roles.CLINIC_ADMIN: set(ALL_PERMISSIONS),
    Roles.RECEPTIONIST: {
        "clinic.view",
        "professional.view",
        "patient.view",
        "patient.add",
        "patient.change",
        "appointment.view",
        "appointment.view_all",
        "appointment.add",
        "appointment.change",
        "appointment.cancel",
        "appointment.payment",
        "document.view",
        "document.add",
        "document.download",
        "examination.view",
        "report.view",
        "service.manage",
        "room.manage",
    },
    Roles.PROFESSIONAL: {
        "clinic.view",
        "professional.view",
        "patient.view",
        "patient.view_sensitive",
        "patient.change",
        "appointment.view",
        "appointment.add",
        "appointment.change",
        "appointment.cancel",
        "schedule.manage",
        "medicalrecord.view",
        "medicalrecord.add",
        "medicalrecord.change",
        "medicalrecord.sign",
        "prescription.add",
        "examination.view",
        "examination.request",
        "examination.result",
        "document.view",
        "document.add",
        "document.download",
        "report.view",
    },
    Roles.PATIENT: set(),  # o portal do paciente usa regras proprias de escopo
}

#: Permissoes que o administrador da clinica NAO pode conceder a si mesmo
#: (exclusivas da plataforma).
PLATFORM_ONLY_ACTIONS = {
    "platform.manage_clinics",
    "platform.manage_plans",
    "platform.view_global_audit",
    "platform.impersonate",
    "platform.settings",
}


def default_permissions_for(role: str) -> Set[str]:
    return set(DEFAULT_ROLE_PERMISSIONS.get(role, set()))
