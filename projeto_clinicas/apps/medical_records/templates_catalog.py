"""
Modelos de prontuario prontos por tipo de clinica.

O prontuario do JJA System e definido por um schema JSON (secoes + campos),
o que permite atender medicina, fisioterapia, estetica, nutricao, psicologia
ou odontologia sem alterar o banco de dados.

Formato do schema::

    {
      "sections": [
        {
          "title": "Anamnese",
          "fields": [
            {"name": "queixa", "label": "Queixa principal",
             "type": "textarea", "required": true},
            {"name": "dor", "label": "Escala de dor", "type": "number"},
            {"name": "lado", "label": "Lado", "type": "select",
             "options": ["Direito", "Esquerdo", "Bilateral"]}
          ]
        }
      ]
    }

Tipos suportados: ``text``, ``textarea``, ``number``, ``date``, ``select``,
``multiselect``, ``checkbox``.
"""
from __future__ import annotations

from typing import Dict, List

from apps.clinics.modules import ClinicType


def _field(name, label, kind="textarea", required=False, options=None, help_text=""):
    field = {"name": name, "label": label, "type": kind, "required": required}
    if options:
        field["options"] = options
    if help_text:
        field["help"] = help_text
    return field


MEDICAL_CONSULTATION = {
    "sections": [
        {
            "title": "Anamnese",
            "fields": [
                _field("queixa_principal", "Queixa principal", required=True),
                _field("historia_doenca_atual", "Historia da doenca atual"),
                _field("antecedentes_pessoais", "Antecedentes pessoais"),
                _field("antecedentes_familiares", "Antecedentes familiares"),
                _field("alergias", "Alergias", "text"),
                _field("medicamentos_em_uso", "Medicamentos em uso"),
                _field("habitos", "Habitos de vida"),
            ],
        },
        {
            "title": "Exame fisico",
            "fields": [
                _field("pressao_arterial", "Pressao arterial (mmHg)", "text"),
                _field("frequencia_cardiaca", "Frequencia cardiaca (bpm)", "number"),
                _field("temperatura", "Temperatura (C)", "text"),
                _field("peso", "Peso (kg)", "number"),
                _field("altura", "Altura (cm)", "number"),
                _field("exame_fisico", "Exame fisico geral"),
            ],
        },
        {
            "title": "Conduta",
            "fields": [
                _field("hipoteses_diagnosticas", "Hipoteses diagnosticas"),
                _field("cid", "CID-10", "text"),
                _field("diagnostico", "Diagnostico"),
                _field("conduta", "Conduta", required=True),
                _field("prescricao", "Prescricao"),
                _field("exames_solicitados", "Exames solicitados"),
                _field("retorno", "Retorno sugerido", "text"),
            ],
        },
    ]
}

PHYSIOTHERAPY_EVALUATION = {
    "sections": [
        {
            "title": "Avaliacao funcional",
            "fields": [
                _field("diagnostico_clinico", "Diagnostico clinico", "text"),
                _field("queixa_principal", "Queixa principal", required=True),
                _field("historia", "Historia da lesao"),
                _field("dor_eva", "Dor (EVA 0-10)", "number"),
                _field("amplitude_movimento", "Amplitude de movimento"),
                _field("forca_muscular", "Forca muscular"),
                _field("testes_especiais", "Testes especiais"),
                _field("marcha_postura", "Marcha e postura"),
            ],
        },
        {
            "title": "Plano terapeutico",
            "fields": [
                _field("objetivos", "Objetivos do tratamento", required=True),
                _field("condutas", "Condutas e recursos"),
                _field("exercicios", "Exercicios prescritos"),
                _field("frequencia_semanal", "Sessoes por semana", "number"),
                _field("total_sessoes", "Total de sessoes previstas", "number"),
            ],
        },
    ]
}

PHYSIOTHERAPY_SESSION = {
    "sections": [
        {
            "title": "Evolucao da sessao",
            "fields": [
                _field("numero_sessao", "Numero da sessao", "number"),
                _field("dor_eva", "Dor (EVA 0-10)", "number"),
                _field("condutas_realizadas", "Condutas realizadas", required=True),
                _field("resposta_paciente", "Resposta do paciente"),
                _field("orientacoes", "Orientacoes / exercicios domiciliares"),
            ],
        }
    ]
}

AESTHETICS_PROCEDURE = {
    "sections": [
        {
            "title": "Avaliacao",
            "fields": [
                _field("queixa_principal", "Queixa principal", required=True),
                _field("fototipo", "Fototipo (Fitzpatrick)", "select",
                       options=["I", "II", "III", "IV", "V", "VI"]),
                _field("historico_procedimentos", "Procedimentos anteriores"),
                _field("contraindicacoes", "Contraindicacoes / alergias"),
            ],
        },
        {
            "title": "Procedimento realizado",
            "fields": [
                _field("procedimento", "Procedimento", "text", required=True),
                _field("regioes_tratadas", "Regioes tratadas", "text"),
                _field("produtos_utilizados", "Produtos utilizados (lote/validade)"),
                _field("parametros", "Parametros do equipamento"),
                _field("intercorrencias", "Intercorrencias"),
                _field("orientacoes_pos", "Orientacoes pos-procedimento"),
                _field("consentimento_foto", "Consentimento para registro fotografico",
                       "checkbox"),
            ],
        },
    ]
}

NUTRITION_CONSULTATION = {
    "sections": [
        {
            "title": "Avaliacao nutricional",
            "fields": [
                _field("objetivo", "Objetivo do paciente", required=True),
                _field("peso", "Peso (kg)", "number"),
                _field("altura", "Altura (cm)", "number"),
                _field("circunferencia_abdominal", "Circunferencia abdominal (cm)", "number"),
                _field("percentual_gordura", "Percentual de gordura (%)", "number"),
                _field("habitos_alimentares", "Habitos alimentares"),
                _field("intolerancias", "Intolerancias e alergias alimentares"),
            ],
        },
        {
            "title": "Plano alimentar",
            "fields": [
                _field("plano_alimentar", "Plano alimentar", required=True),
                _field("suplementacao", "Suplementacao"),
                _field("metas", "Metas ate o retorno"),
            ],
        },
    ]
}

PSYCHOLOGY_SESSION = {
    "sections": [
        {
            "title": "Registro da sessao",
            "fields": [
                _field("numero_sessao", "Numero da sessao", "number"),
                _field("demanda", "Demanda trabalhada", required=True),
                _field("intervencoes", "Intervencoes realizadas"),
                _field("evolucao", "Evolucao observada"),
                _field("encaminhamentos", "Encaminhamentos"),
                _field("proximos_passos", "Planejamento para a proxima sessao"),
            ],
        }
    ]
}

DENTAL_CONSULTATION = {
    "sections": [
        {
            "title": "Anamnese odontologica",
            "fields": [
                _field("queixa_principal", "Queixa principal", required=True),
                _field("historico_medico", "Historico medico relevante"),
                _field("higiene_oral", "Higiene oral"),
            ],
        },
        {
            "title": "Exame e plano",
            "fields": [
                _field("exame_clinico", "Exame clinico"),
                _field("dentes_envolvidos", "Dentes envolvidos (FDI)", "text"),
                _field("plano_tratamento", "Plano de tratamento", required=True),
                _field("procedimento_realizado", "Procedimento realizado"),
                _field("materiais", "Materiais utilizados"),
            ],
        },
    ]
}

GENERIC_EVOLUTION = {
    "sections": [
        {
            "title": "Atendimento",
            "fields": [
                _field("motivo", "Motivo do atendimento", required=True),
                _field("avaliacao", "Avaliacao"),
                _field("conduta", "Conduta", required=True),
                _field("orientacoes", "Orientacoes"),
            ],
        }
    ]
}


#: tipo de clinica -> lista de (nome, schema, e_padrao)
DEFAULT_TEMPLATES: Dict[str, List[tuple]] = {
    ClinicType.MEDICAL: [
        ("Consulta medica", MEDICAL_CONSULTATION, True),
        ("Evolucao / retorno", GENERIC_EVOLUTION, False),
    ],
    ClinicType.PHYSIOTHERAPY: [
        ("Avaliacao fisioterapeutica", PHYSIOTHERAPY_EVALUATION, True),
        ("Sessao de fisioterapia", PHYSIOTHERAPY_SESSION, False),
    ],
    ClinicType.AESTHETICS: [
        ("Procedimento estetico", AESTHETICS_PROCEDURE, True),
        ("Evolucao", GENERIC_EVOLUTION, False),
    ],
    ClinicType.DERMATOLOGY: [
        ("Consulta dermatologica", MEDICAL_CONSULTATION, True),
        ("Procedimento", AESTHETICS_PROCEDURE, False),
    ],
    ClinicType.NUTRITION: [
        ("Consulta nutricional", NUTRITION_CONSULTATION, True),
        ("Retorno", GENERIC_EVOLUTION, False),
    ],
    ClinicType.PSYCHOLOGY: [
        ("Sessao de psicologia", PSYCHOLOGY_SESSION, True),
    ],
    ClinicType.DENTAL: [
        ("Consulta odontologica", DENTAL_CONSULTATION, True),
    ],
    ClinicType.MULTIDISCIPLINARY: [
        ("Consulta medica", MEDICAL_CONSULTATION, True),
        ("Avaliacao fisioterapeutica", PHYSIOTHERAPY_EVALUATION, False),
        ("Consulta nutricional", NUTRITION_CONSULTATION, False),
        ("Sessao de psicologia", PSYCHOLOGY_SESSION, False),
    ],
    ClinicType.DIAGNOSTIC: [("Laudo / atendimento", GENERIC_EVOLUTION, True)],
    ClinicType.VETERINARY: [("Consulta veterinaria", MEDICAL_CONSULTATION, True)],
    ClinicType.OTHER: [("Atendimento", GENERIC_EVOLUTION, True)],
}


def templates_for(clinic_type: str) -> List[tuple]:
    return DEFAULT_TEMPLATES.get(clinic_type, DEFAULT_TEMPLATES[ClinicType.OTHER])
