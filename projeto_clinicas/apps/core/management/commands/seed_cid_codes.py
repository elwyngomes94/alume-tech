"""
Popula um conjunto curado de codigos CID-10 de uso frequente, usados no
autocomplete de diagnostico do prontuario.

Nao e a tabela completa da OMS/DATASUS (~14 mil codigos) -- o campo de
diagnostico sempre aceita texto livre tambem, entao a ausencia de um codigo
aqui nunca bloqueia o profissional. Idempotente (``get_or_create``).

Uso:
    python manage.py seed_cid_codes
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.medical_records.models import CIDCode

#: (codigo, descricao) -- conjunto curado dos codigos mais usados no dia a
#: dia clinico (clinica geral, cardio, respiratorio, endocrino, saude
#: mental, gestacao, lesoes e sintomas frequentes).
CID_CODES = [
    # Infecciosas / parasitarias
    ("A09", "Diarreia e gastroenterite de origem infecciosa presumivel"),
    ("A90", "Dengue [dengue classico]"),
    ("A91", "Febre hemorragica devida ao virus do dengue"),
    ("B34.9", "Infeccao viral nao especificada"),
    ("B86", "Escabiose"),
    # Neoplasias (rastreamento/acompanhamento comuns)
    ("Z12.1", "Exame de rastreamento para neoplasia do trato digestivo"),
    ("Z12.4", "Exame de rastreamento para neoplasia do colo do utero"),
    ("Z12.31", "Exame de rastreamento para neoplasia da mama"),
    # Sangue
    ("D50.9", "Anemia por deficiencia de ferro nao especificada"),
    ("D64.9", "Anemia nao especificada"),
    # Endocrino / metabolico
    ("E03.9", "Hipotireoidismo nao especificado"),
    ("E05.9", "Tireotoxicose nao especificada"),
    ("E10", "Diabetes mellitus tipo 1"),
    ("E11", "Diabetes mellitus tipo 2"),
    ("E11.9", "Diabetes mellitus tipo 2 sem complicacoes"),
    ("E66.0", "Obesidade devida a excesso de calorias"),
    ("E66.9", "Obesidade nao especificada"),
    ("E78.0", "Hipercolesterolemia pura"),
    ("E78.5", "Hiperlipidemia nao especificada"),
    ("E86", "Depleção de volume (desidratacao)"),
    # Transtornos mentais
    ("F32.0", "Episodio depressivo leve"),
    ("F32.1", "Episodio depressivo moderado"),
    ("F32.9", "Episodio depressivo nao especificado"),
    ("F33.9", "Transtorno depressivo recorrente nao especificado"),
    ("F41.0", "Transtorno de panico"),
    ("F41.1", "Transtorno de ansiedade generalizada"),
    ("F41.9", "Transtorno de ansiedade nao especificado"),
    ("F43.1", "Transtorno de estresse pos-traumatico"),
    ("F43.2", "Transtornos de adaptacao"),
    ("F51.0", "Insonia nao organica"),
    ("F90.0", "Perturbacao da atividade e da atencao (TDAH)"),
    # Sistema nervoso
    ("G43.9", "Enxaqueca nao especificada"),
    ("G47.0", "Disturbios de iniciar e manter o sono"),
    ("G47.9", "Disturbio do sono nao especificado"),
    # Olhos / ouvidos
    ("H10.9", "Conjuntivite nao especificada"),
    ("H52.1", "Miopia"),
    ("H52.4", "Presbiopia"),
    ("H61.2", "Cerumen impactado"),
    ("H66.9", "Otite media nao especificada"),
    ("H81.1", "Vertigem posicional paroxistica benigna"),
    # Cardiovascular
    ("I10", "Hipertensao essencial (primaria)"),
    ("I20.0", "Angina instavel"),
    ("I21.9", "Infarto agudo do miocardio nao especificado"),
    ("I25.9", "Doenca isquemica cronica do coracao nao especificada"),
    ("I48", "Fibrilacao e flutter atrial"),
    ("I50.0", "Insuficiencia cardiaca congestiva"),
    ("I50.9", "Insuficiencia cardiaca nao especificada"),
    ("I63.9", "Acidente vascular cerebral isquemico nao especificado"),
    ("I80.2", "Flebite e tromboflebite de outros vasos profundos"),
    ("I83.9", "Varizes dos membros inferiores sem ulcera ou inflamacao"),
    ("I84.9", "Hemorroidas nao especificadas"),
    # Respiratorio
    ("J00", "Nasofaringite aguda [resfriado comum]"),
    ("J01.9", "Sinusite aguda nao especificada"),
    ("J02.9", "Faringite aguda nao especificada"),
    ("J03.9", "Amigdalite aguda nao especificada"),
    ("J06.9", "Infeccao aguda das vias aereas superiores nao especificada"),
    ("J11.1", "Influenza com outras manifestacoes respiratorias"),
    ("J18.9", "Pneumonia nao especificada"),
    ("J20.9", "Bronquite aguda nao especificada"),
    ("J30.4", "Rinite alergica nao especificada"),
    ("J35.0", "Amigdalite cronica"),
    ("J44.9", "Doenca pulmonar obstrutiva cronica nao especificada"),
    ("J45.9", "Asma nao especificada"),
    ("J46", "Estado de mal asmatico"),
    # Digestivo
    ("K02.9", "Carie dentaria nao especificada"),
    ("K21.0", "Doenca do refluxo gastroesofagico com esofagite"),
    ("K21.9", "Doenca do refluxo gastroesofagico sem esofagite"),
    ("K29.7", "Gastrite nao especificada"),
    ("K30", "Dispepsia"),
    ("K35.9", "Apendicite aguda nao especificada"),
    ("K52.9", "Gastroenterite e colite nao infecciosas nao especificadas"),
    ("K57.9", "Doenca diverticular do intestino sem especificacao"),
    ("K59.0", "Constipacao"),
    ("K59.1", "Diarreia funcional"),
    ("K80.2", "Calculo da vesicula biliar sem colecistite"),
    ("K92.2", "Hemorragia gastrointestinal nao especificada"),
    # Pele
    ("L03.9", "Celulite nao especificada"),
    ("L20.9", "Dermatite atopica nao especificada"),
    ("L23.9", "Dermatite alergica de contato de causa nao especificada"),
    ("L30.9", "Dermatite nao especificada"),
    ("L50.9", "Urticaria nao especificada"),
    ("L70.0", "Acne vulgar"),
    ("L98.9", "Afeccao da pele e do tecido subcutaneo nao especificada"),
    # Osteomuscular
    ("M25.5", "Dor articular"),
    ("M45", "Espondilite ancilosante"),
    ("M51.9", "Transtorno de disco intervertebral nao especificado"),
    ("M54.2", "Cervicalgia"),
    ("M54.5", "Dor lombar baixa"),
    ("M54.9", "Dorsalgia nao especificada"),
    ("M62.6", "Distensao muscular"),
    ("M75.1", "Sindrome do manguito rotador"),
    ("M79.1", "Mialgia"),
    ("M79.7", "Fibromialgia"),
    # Genito-urinario
    ("N30.9", "Cistite nao especificada"),
    ("N39.0", "Infeccao do trato urinario nao especificada"),
    ("N40", "Hiperplasia da prostata"),
    ("N76.0", "Vaginite aguda"),
    ("N92.6", "Menstruacao irregular nao especificada"),
    ("N94.6", "Dismenorreia nao especificada"),
    # Gravidez / puerperio
    ("Z34.9", "Supervisao de gravidez normal nao especificada"),
    ("O23.9", "Infeccao nao especificada do trato urinario na gravidez"),
    ("O26.9", "Afeccao nao especificada relacionada com a gravidez"),
    ("O80", "Parto unico espontaneo"),
    ("Z39.2", "Assistencia ao puerperio de rotina"),
    # Sintomas e sinais gerais
    ("R05", "Tosse"),
    ("R06.0", "Dispneia"),
    ("R07.4", "Dor no peito nao especificada"),
    ("R10.4", "Outras dores abdominais e as nao especificadas"),
    ("R11", "Nausea e vomitos"),
    ("R42", "Tontura e instabilidade"),
    ("R50.9", "Febre nao especificada"),
    ("R51", "Cefaleia"),
    ("R53", "Mal estar e fadiga"),
    ("R55", "Sincope e colapso"),
    ("R56.8", "Outras convulsoes e as nao especificadas"),
    ("R60.0", "Edema localizado"),
    ("R63.4", "Perda de peso anormal"),
    # Lesoes / causas externas
    ("S00.9", "Traumatismo superficial da cabeca nao especificado"),
    ("S06.0", "Concussao cerebral"),
    ("S09.9", "Traumatismo da cabeca nao especificado"),
    ("S13.4", "Entorse e distensao dos ligamentos cervicais"),
    ("S43.4", "Entorse e distensao da articulacao do ombro"),
    ("S52.9", "Fratura do antebraco nao especificada"),
    ("S60.9", "Traumatismo superficial do punho e da mao nao especificado"),
    ("S61.9", "Ferimento do punho e da mao nao especificado"),
    ("S72.9", "Fratura do femur nao especificada"),
    ("S82.9", "Fratura da perna nao especificada"),
    ("S93.4", "Entorse e distensao do tornozelo"),
    ("T14.9", "Traumatismo nao especificado"),
    ("T78.4", "Alergia nao especificada"),
    # Fatores que influenciam o estado de saude / consultas de rotina
    ("Z00.0", "Exame medico geral"),
    ("Z01.4", "Exame ginecologico geral"),
    ("Z23", "Necessidade de imunizacao contra doenca bacteriana unica"),
    ("Z71.3", "Aconselhamento dietetico e vigilancia"),
    ("Z76.0", "Prescricao ou renovacao de receita"),
]


class Command(BaseCommand):
    help = "Popula o catalogo curado de codigos CID-10 usado no autocomplete do prontuario."

    def handle(self, *args, **options):
        created = 0
        for code, description in CID_CODES:
            _obj, was_created = CIDCode.objects.get_or_create(
                code=code, defaults={"description": description},
            )
            if was_created:
                created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"{created} codigo(s) CID criado(s) ({len(CID_CODES)} no catalogo)."
            )
        )
