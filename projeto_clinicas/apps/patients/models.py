"""Cadastro de pacientes (dados pessoais e dados pessoais sensiveis)."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.models import TenantModel
from apps.core.utils import calculate_age, format_document, mask_document
from apps.core.validators import validate_cep, validate_cpf, validate_phone


class Patient(TenantModel):
    """
    Paciente de uma clinica.

    Um mesmo CPF pode existir em clinicas diferentes: cada clinica possui o seu
    proprio cadastro, sem qualquer compartilhamento de dados entre elas.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"
        ARCHIVED = "archived", "Arquivado"

    class Gender(models.TextChoices):
        FEMALE = "F", "Feminino"
        MALE = "M", "Masculino"
        OTHER = "O", "Outro"
        NOT_INFORMED = "N", "Nao informado"

    record_number = models.PositiveIntegerField("prontuario", editable=False, db_index=True)
    full_name = models.CharField("nome completo", max_length=180, db_index=True)
    social_name = models.CharField("nome social", max_length=180, blank=True)
    cpf = models.CharField("CPF", max_length=14, blank=True, validators=[validate_cpf])
    rg = models.CharField("RG", max_length=20, blank=True)
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    gender = models.CharField(
        "sexo/genero", max_length=1, choices=Gender.choices, default=Gender.NOT_INFORMED
    )
    marital_status = models.CharField("estado civil", max_length=40, blank=True)
    occupation = models.CharField("profissao", max_length=80, blank=True)
    nationality = models.CharField("nacionalidade", max_length=60, blank=True)

    # Contato
    email = models.EmailField("e-mail", blank=True)
    phone = models.CharField("telefone", max_length=20, blank=True, validators=[validate_phone])
    mobile = models.CharField("celular", max_length=20, blank=True, validators=[validate_phone])
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)

    # Dados de saude (dado pessoal sensivel - LGPD art. 5, II)
    blood_type = models.CharField("tipo sanguineo", max_length=5, blank=True)
    allergies = models.TextField("alergias", blank=True)
    chronic_conditions = models.TextField("condicoes cronicas", blank=True)
    continuous_medications = models.TextField("medicamentos de uso continuo", blank=True)
    health_notes = models.TextField("observacoes de saude", blank=True)

    # Convenio
    insurance = models.ForeignKey(
        "clinics.InsurancePlan",
        verbose_name="convenio",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patients",
    )
    insurance_number = models.CharField("numero da carteirinha", max_length=60, blank=True)

    # Responsavel legal (menores de idade / incapazes)
    guardian_name = models.CharField("responsavel legal", max_length=180, blank=True)
    guardian_document = models.CharField("CPF do responsavel", max_length=14, blank=True)
    guardian_phone = models.CharField("telefone do responsavel", max_length=20, blank=True)
    guardian_relationship = models.CharField("parentesco", max_length=60, blank=True)

    # Acesso ao portal
    portal_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario do portal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
    )

    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    referral_source = models.CharField("como conheceu a clinica", max_length=80, blank=True)
    notes = models.TextField("observacoes administrativas", blank=True)
    photo = models.ImageField("foto", upload_to="patients/photos/", null=True, blank=True)

    class Meta:
        verbose_name = "paciente"
        verbose_name_plural = "pacientes"
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "cpf"],
                condition=models.Q(is_deleted=False) & ~models.Q(cpf=""),
                name="uniq_patient_cpf_per_clinic",
            ),
            models.UniqueConstraint(
                fields=["clinic", "record_number"], name="uniq_patient_record_per_clinic"
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "full_name"]),
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["cpf"]),
        ]

    def __str__(self) -> str:
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.record_number:
            self.record_number = self._next_record_number()
        return super().save(*args, **kwargs)

    def _next_record_number(self) -> int:
        from apps.core.tenancy import get_current_tenant_id

        clinic_id = self.clinic_id or get_current_tenant_id()
        last = (
            Patient.all_objects.filter(clinic_id=clinic_id)
            .order_by("-record_number")
            .values_list("record_number", flat=True)
            .first()
        )
        return (last or 0) + 1

    # -- apresentacao -------------------------------------------------------
    @property
    def display_name(self) -> str:
        return self.social_name or self.full_name

    @property
    def age(self):
        return calculate_age(self.birth_date)

    @property
    def is_minor(self) -> bool:
        age = self.age
        return age is not None and age < 18

    @property
    def formatted_cpf(self) -> str:
        return format_document(self.cpf)

    @property
    def masked_cpf(self) -> str:
        """Usado em listagens (principio da minimizacao de dados)."""
        return mask_document(self.cpf)

    @property
    def primary_phone(self) -> str:
        return self.mobile or self.phone or self.whatsapp

    def get_absolute_url(self) -> str:
        return reverse("patients:detail", args=[self.pk])


class PatientAddress(TenantModel):
    class Kind(models.TextChoices):
        HOME = "home", "Residencial"
        WORK = "work", "Comercial"
        OTHER = "other", "Outro"

    patient = models.ForeignKey(
        Patient, verbose_name="paciente", on_delete=models.CASCADE, related_name="addresses"
    )
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.HOME)
    postal_code = models.CharField("CEP", max_length=9, blank=True, validators=[validate_cep])
    street = models.CharField("logradouro", max_length=180, blank=True)
    number = models.CharField("numero", max_length=20, blank=True)
    complement = models.CharField("complemento", max_length=80, blank=True)
    district = models.CharField("bairro", max_length=100, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    is_primary = models.BooleanField("principal", default=True)

    class Meta:
        verbose_name = "endereco do paciente"
        verbose_name_plural = "enderecos do paciente"
        ordering = ["-is_primary", "kind"]

    def __str__(self) -> str:
        return f"{self.street}, {self.number} - {self.city}/{self.state}".strip(" ,-")


class PatientContact(TenantModel):
    """Contato de emergencia ou responsavel adicional."""

    patient = models.ForeignKey(
        Patient, verbose_name="paciente", on_delete=models.CASCADE, related_name="contacts"
    )
    name = models.CharField("nome", max_length=180)
    relationship = models.CharField("parentesco/relacao", max_length=60, blank=True)
    phone = models.CharField("telefone", max_length=20, validators=[validate_phone])
    email = models.EmailField("e-mail", blank=True)
    is_emergency = models.BooleanField("contato de emergencia", default=True)
    notes = models.CharField("observacao", max_length=200, blank=True)

    class Meta:
        verbose_name = "contato do paciente"
        verbose_name_plural = "contatos do paciente"
        ordering = ["-is_emergency", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.relationship})" if self.relationship else self.name
