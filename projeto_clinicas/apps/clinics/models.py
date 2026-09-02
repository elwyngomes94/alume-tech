"""Clinica (tenant), suas configuracoes e cadastros auxiliares."""
from __future__ import annotations

from datetime import time
from typing import List

from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from apps.clinics.modules import ClinicType, default_modules_for
from apps.core.models import ActiveStatusMixin, BaseModel, TenantModel
from apps.core.storage import clinic_logo_path
from apps.core.validators import (
    validate_cep,
    validate_cpf_or_cnpj,
    validate_hex_color,
    validate_image_upload,
    validate_phone,
)

UF_CHOICES = [
    (uf, uf)
    for uf in [
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
        "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
        "SP", "SE", "TO",
    ]
]


class Clinic(BaseModel):
    """
    Tenant do JJA System.

    Todos os dados operacionais (pacientes, agendas, prontuarios, documentos)
    referenciam obrigatoriamente uma clinica.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        TRIAL = "trial", "Em avaliacao"
        SUSPENDED = "suspended", "Suspensa"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(
        "tenants.Organization",
        verbose_name="organizacao",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinics",
    )

    legal_name = models.CharField("razao social", max_length=180)
    trade_name = models.CharField("nome fantasia", max_length=180)
    slug = models.SlugField("identificador (slug)", max_length=180, unique=True)
    document = models.CharField(
        "CNPJ/CPF", max_length=18, unique=True, validators=[validate_cpf_or_cnpj]
    )
    clinic_type = models.CharField(
        "tipo de clinica", max_length=32, choices=ClinicType.CHOICES, default=ClinicType.MEDICAL
    )
    logo = models.ImageField(
        "logotipo", upload_to=clinic_logo_path, blank=True, null=True,
        validators=[validate_image_upload],
    )

    # Endereco
    address = models.CharField("logradouro", max_length=180, blank=True)
    address_number = models.CharField("numero", max_length=20, blank=True)
    address_complement = models.CharField("complemento", max_length=80, blank=True)
    district = models.CharField("bairro", max_length=100, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("estado", max_length=2, choices=UF_CHOICES, blank=True)
    postal_code = models.CharField("CEP", max_length=9, blank=True, validators=[validate_cep])

    # Contato
    phone = models.CharField("telefone", max_length=20, blank=True, validators=[validate_phone])
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)
    email = models.EmailField("e-mail", blank=True)
    website = models.URLField("site", blank=True)

    # Responsavel tecnico
    responsible_name = models.CharField("responsavel", max_length=180, blank=True)
    responsible_document = models.CharField("CPF do responsavel", max_length=14, blank=True)
    professional_registry = models.CharField(
        "registro profissional (CRM/CRO/CREFITO/CRP...)", max_length=40, blank=True
    )

    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.TRIAL, db_index=True
    )
    modules = models.JSONField("modulos habilitados", default=list, blank=True)
    notes = models.TextField("observacoes internas", blank=True)

    class Meta:
        verbose_name = "clinica"
        verbose_name_plural = "clinicas"
        ordering = ["trade_name"]
        indexes = [
            models.Index(fields=["status", "clinic_type"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self) -> str:
        return self.trade_name or self.legal_name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.trade_name or self.legal_name)[:170] or "clinica"
            slug, counter = base, 1
            while Clinic.all_objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base}-{counter}"
            self.slug = slug
        if not self.modules:
            self.modules = default_modules_for(self.clinic_type)
        return super().save(*args, **kwargs)

    # -- estado -------------------------------------------------------------
    @property
    def is_operational(self) -> bool:
        """Clinicas suspensas/canceladas nao operam."""
        return self.status in (self.Status.ACTIVE, self.Status.TRIAL) and not self.is_deleted

    def has_module(self, codename: str) -> bool:
        return codename in (self.modules or [])

    def enabled_modules(self) -> List[str]:
        return list(self.modules or [])

    @property
    def has_module_finance(self) -> bool:
        """
        Atalho para templates: ``{% if clinic.has_module_finance %}``.

        Django Templates nao permitem passar argumentos para metodos
        (``has_module("finance")`` nao funciona direto no template), entao
        expomos essa checagem especifica como property.
        """
        return self.has_module("finance")

    @property
    def has_module_automation(self) -> bool:
        """Atalho para templates, mesmo motivo de ``has_module_finance``."""
        return self.has_module("automation")

    @property
    def has_module_inventory(self) -> bool:
        """Atalho para templates, mesmo motivo de ``has_module_finance``."""
        return self.has_module("inventory")

    @property
    def has_module_calling(self) -> bool:
        """Atalho para templates, mesmo motivo de ``has_module_finance``."""
        return self.has_module("patient_calling")

    def get_absolute_url(self) -> str:
        return reverse("platform:clinic-detail", args=[self.pk])

    @property
    def full_address(self) -> str:
        parts = [
            f"{self.address}, {self.address_number}".strip(", "),
            self.address_complement,
            self.district,
            f"{self.city}/{self.state}".strip("/"),
            self.postal_code,
        ]
        return " - ".join(p for p in parts if p)

    @property
    def primary_color(self) -> str:
        settings_obj = getattr(self, "settings", None)
        return settings_obj.primary_color if settings_obj else "#0b5ed7"


class ClinicSettings(BaseModel):
    """Configuracoes e identidade visual proprias de cada clinica."""

    clinic = models.OneToOneField(
        Clinic, on_delete=models.CASCADE, related_name="settings", verbose_name="clinica"
    )
    primary_color = models.CharField(
        "cor primaria", max_length=7, default="#0b5ed7", validators=[validate_hex_color]
    )
    secondary_color = models.CharField(
        "cor secundaria", max_length=7, default="#0dcaf0", validators=[validate_hex_color]
    )

    # Agenda
    appointment_duration = models.PositiveIntegerField("duracao padrao (min)", default=30)
    opening_time = models.TimeField("abertura", default=time(8, 0))
    closing_time = models.TimeField("fechamento", default=time(18, 0))
    working_days = models.JSONField("dias de funcionamento", default=list, blank=True)
    allow_overbooking = models.BooleanField("permitir encaixe", default=True)
    allow_patient_scheduling = models.BooleanField(
        "paciente pode solicitar agendamento", default=True
    )
    patient_cancel_hours = models.PositiveIntegerField(
        "antecedencia minima para cancelar (h)", default=24
    )

    # Notificacoes
    notify_email = models.BooleanField("notificar por e-mail", default=True)
    notify_whatsapp = models.BooleanField("notificar por WhatsApp", default=False)
    notify_sms = models.BooleanField("notificar por SMS", default=False)
    reminder_hours_before = models.PositiveIntegerField("lembrete (h antes)", default=24)

    # Prontuario / LGPD
    record_lock_hours = models.PositiveIntegerField(
        "prazo para editar registro assinado (h)", default=24
    )
    require_photo_consent = models.BooleanField("exigir consentimento para fotos", default=True)
    data_retention_years = models.PositiveIntegerField("retencao de prontuario (anos)", default=20)

    class Meta:
        verbose_name = "configuracao da clinica"
        verbose_name_plural = "configuracoes das clinicas"

    def __str__(self) -> str:
        return f"Configuracoes de {self.clinic}"

    def save(self, *args, **kwargs):
        if not self.working_days:
            self.working_days = [0, 1, 2, 3, 4]  # segunda a sexta
        return super().save(*args, **kwargs)


class Specialty(TenantModel, ActiveStatusMixin):
    """Especialidade atendida pela clinica."""

    name = models.CharField("nome", max_length=120)
    description = models.TextField("descricao", blank=True)
    color = models.CharField(
        "cor na agenda", max_length=7, default="#6c757d", validators=[validate_hex_color]
    )

    class Meta:
        verbose_name = "especialidade"
        verbose_name_plural = "especialidades"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_specialty_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Service(TenantModel, ActiveStatusMixin):
    """Servico/procedimento oferecido (consulta, sessao, exame, procedimento)."""

    name = models.CharField("nome", max_length=140)
    code = models.CharField("codigo interno", max_length=40, blank=True)
    specialty = models.ForeignKey(
        Specialty,
        verbose_name="especialidade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
    )
    duration_minutes = models.PositiveIntegerField("duracao (min)", default=30)
    price = models.DecimalField("valor", max_digits=10, decimal_places=2, default=0)
    requires_room = models.BooleanField("exige sala", default=False)
    description = models.TextField("descricao", blank=True)

    class Meta:
        verbose_name = "servico"
        verbose_name_plural = "servicos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_service_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Room(TenantModel, ActiveStatusMixin):
    """Sala/consultorio da clinica."""

    name = models.CharField("nome", max_length=80)
    identifier = models.CharField("identificacao", max_length=40, blank=True)
    capacity = models.PositiveIntegerField("capacidade", default=1)
    notes = models.CharField("observacoes", max_length=200, blank=True)

    class Meta:
        verbose_name = "sala"
        verbose_name_plural = "salas"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_room_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class InsurancePlan(TenantModel, ActiveStatusMixin):
    """Convenio aceito pela clinica."""

    name = models.CharField("convenio", max_length=120)
    registry_code = models.CharField("registro ANS", max_length=40, blank=True)
    contact = models.CharField("contato", max_length=120, blank=True)
    notes = models.TextField("observacoes", blank=True)

    class Meta:
        verbose_name = "convenio"
        verbose_name_plural = "convenios"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_insurance_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name
