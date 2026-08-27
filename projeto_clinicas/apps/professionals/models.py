"""Cadastro de profissionais vinculados a uma clinica."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.models import ActiveStatusMixin, TenantModel
from apps.core.validators import validate_cep, validate_cpf, validate_phone

COUNCIL_CHOICES = [
    ("CRM", "CRM - Medicina"),
    ("CRO", "CRO - Odontologia"),
    ("CREFITO", "CREFITO - Fisioterapia"),
    ("CRP", "CRP - Psicologia"),
    ("CRN", "CRN - Nutricao"),
    ("COREN", "COREN - Enfermagem"),
    ("CRBM", "CRBM - Biomedicina"),
    ("CRMV", "CRMV - Medicina Veterinaria"),
    ("CREF", "CREF - Educacao Fisica"),
    ("OUTRO", "Outro"),
]


class Professional(TenantModel, ActiveStatusMixin):
    """
    Profissional que realiza atendimentos.

    O mesmo usuario pode ser profissional em varias clinicas: cada vinculo
    gera um registro proprio, com agenda, servicos e dados independentes.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario de acesso",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="professional_profiles",
    )
    full_name = models.CharField("nome completo", max_length=180, db_index=True)
    social_name = models.CharField("nome de tratamento", max_length=180, blank=True)
    cpf = models.CharField("CPF", max_length=14, blank=True, validators=[validate_cpf])
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    email = models.EmailField("e-mail", blank=True)
    phone = models.CharField("telefone", max_length=20, blank=True, validators=[validate_phone])
    photo = models.ImageField("foto", upload_to="professionals/photos/", null=True, blank=True)

    # Endereco (mesmo padrao de nomes de apps.clinics.models.Clinic)
    address = models.CharField("logradouro", max_length=180, blank=True)
    address_number = models.CharField("numero", max_length=20, blank=True)
    address_complement = models.CharField("complemento", max_length=80, blank=True)
    district = models.CharField("bairro", max_length=100, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("estado", max_length=2, blank=True)
    postal_code = models.CharField("CEP", max_length=9, blank=True, validators=[validate_cep])

    council = models.CharField("conselho", max_length=20, choices=COUNCIL_CHOICES, blank=True)
    registry_number = models.CharField("registro profissional", max_length=40, blank=True)
    registry_state = models.CharField("UF do registro", max_length=2, blank=True)

    specialties = models.ManyToManyField(
        "clinics.Specialty", verbose_name="especialidades", blank=True, related_name="professionals"
    )
    subspecialty = models.CharField("subespecialidade", max_length=120, blank=True)
    services = models.ManyToManyField(
        "clinics.Service", verbose_name="servicos realizados", blank=True,
        related_name="professionals",
    )
    rooms = models.ManyToManyField(
        "clinics.Room", verbose_name="salas", blank=True, related_name="professionals"
    )

    biography = models.TextField("biografia", blank=True)
    appointment_duration = models.PositiveIntegerField("duracao padrao (min)", default=30)
    accepts_online_scheduling = models.BooleanField(
        "aceita solicitacao pelo portal do paciente", default=True
    )
    notes = models.TextField("observacoes internas", blank=True)

    class Meta:
        verbose_name = "profissional"
        verbose_name_plural = "profissionais"
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "user"],
                condition=models.Q(is_deleted=False) & models.Q(user__isnull=False),
                name="uniq_professional_user_per_clinic",
            )
        ]
        indexes = [models.Index(fields=["clinic", "is_active"])]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.social_name or self.full_name

    @property
    def registry_label(self) -> str:
        if not self.registry_number:
            return ""
        parts = [self.council, self.registry_number]
        if self.registry_state:
            parts.append(f"/{self.registry_state}")
        return " ".join(p for p in parts if p).replace(" /", "/")

    @property
    def specialty_names(self) -> str:
        return ", ".join(specialty.name for specialty in self.specialties.all())

    def get_absolute_url(self) -> str:
        return reverse("professionals:detail", args=[self.pk])
