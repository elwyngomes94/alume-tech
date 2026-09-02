"""
Tipos de clinica e modulos habilitaveis.

O JJA System nao e amarrado a uma profissao: o tipo de clinica define quais
modulos ficam ativos e quais modelos de prontuario sao sugeridos. Novos tipos
podem ser adicionados aqui sem qualquer alteracao estrutural no sistema.
"""
from __future__ import annotations

from typing import Dict, List, Set


class ClinicType:
    MEDICAL = "medica"
    PHYSIOTHERAPY = "fisioterapia"
    DENTAL = "odontologica"
    PSYCHOLOGY = "psicologia"
    NUTRITION = "nutricao"
    AESTHETICS = "estetica"
    DERMATOLOGY = "dermatologia"
    DIAGNOSTIC = "exames"
    MULTIDISCIPLINARY = "multidisciplinar"
    VETERINARY = "veterinaria"
    OTHER = "outro"

    CHOICES = [
        (MEDICAL, "Clinica medica"),
        (PHYSIOTHERAPY, "Fisioterapia"),
        (DENTAL, "Odontologica"),
        (PSYCHOLOGY, "Psicologia"),
        (NUTRITION, "Nutricao"),
        (AESTHETICS, "Estetica"),
        (DERMATOLOGY, "Dermatologia"),
        (DIAGNOSTIC, "Clinica de exames"),
        (MULTIDISCIPLINARY, "Multidisciplinar"),
        (VETERINARY, "Veterinaria"),
        (OTHER, "Outro"),
    ]


#: codename -> (rotulo, descricao)
MODULE_CATALOG: Dict[str, tuple] = {
    "scheduling": ("Agenda", "Agendamentos, disponibilidade e bloqueios"),
    "medical_records": ("Prontuario", "Registro clinico eletronico"),
    "prescriptions": ("Prescricoes", "Emissao de receitas e orientacoes"),
    "examinations": ("Exames", "Solicitacao e resultados de exames"),
    "documents": ("Documentos", "Anexos, laudos e termos"),
    "therapy_plan": ("Plano terapeutico", "Avaliacao funcional, objetivos e sessoes"),
    "procedures": ("Procedimentos", "Procedimentos esteticos, produtos e regioes"),
    "clinical_photos": ("Fotografias clinicas", "Registro fotografico com consentimento"),
    "consent_terms": ("Termos de consentimento", "Termos especificos por procedimento"),
    "nutrition_plan": ("Plano alimentar", "Antropometria e plano alimentar"),
    "psych_sessions": ("Sessoes de psicologia", "Evolucao de sessoes com sigilo reforcado"),
    "odontogram": ("Odontograma", "Mapa dentario e plano de tratamento"),
    "reports": ("Relatorios", "Relatorios e indicadores"),
    "patient_portal": ("Portal do paciente", "Acesso do paciente aos proprios dados"),
    "billing": ("Faturamento", "Plano, faturas e limites"),
    "finance": ("Financeiro", "Contas a receber, contas a pagar e fluxo de caixa"),
    "automation": ("Automacao", "Lista de espera automatica, baixa por webhook e comprovantes"),
    "inventory": ("Estoque", "Produtos, entradas/saidas e controle de estoque minimo"),
    "patient_calling": ("Chamada de pacientes", "Senha, painel de chamada e Web Push"),
}

#: Modulos ativos por padrao em qualquer clinica.
BASE_MODULES: Set[str] = {
    "scheduling",
    "medical_records",
    "documents",
    "reports",
    "patient_portal",
    "finance",
    "automation",
}

DEFAULT_MODULES_BY_TYPE: Dict[str, Set[str]] = {
    ClinicType.MEDICAL: BASE_MODULES | {"prescriptions", "examinations"},
    ClinicType.PHYSIOTHERAPY: BASE_MODULES | {"therapy_plan"},
    ClinicType.DENTAL: BASE_MODULES | {"odontogram", "procedures", "consent_terms"},
    ClinicType.PSYCHOLOGY: BASE_MODULES | {"psych_sessions"},
    ClinicType.NUTRITION: BASE_MODULES | {"nutrition_plan"},
    ClinicType.AESTHETICS: BASE_MODULES
    | {"procedures", "clinical_photos", "consent_terms"},
    ClinicType.DERMATOLOGY: BASE_MODULES
    | {"prescriptions", "procedures", "clinical_photos", "examinations"},
    ClinicType.DIAGNOSTIC: BASE_MODULES | {"examinations"},
    ClinicType.MULTIDISCIPLINARY: BASE_MODULES
    | {"prescriptions", "examinations", "therapy_plan", "nutrition_plan", "procedures"},
    ClinicType.VETERINARY: BASE_MODULES | {"prescriptions", "examinations"},
    ClinicType.OTHER: BASE_MODULES,
}


def default_modules_for(clinic_type: str) -> List[str]:
    return sorted(DEFAULT_MODULES_BY_TYPE.get(clinic_type, BASE_MODULES))


def module_label(codename: str) -> str:
    return MODULE_CATALOG.get(codename, (codename, ""))[0]
