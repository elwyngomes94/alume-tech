"""Documentos e anexos com armazenamento privado e controle de acesso."""
from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import models

from apps.core.models import ActiveStatusMixin, TenantModel
from apps.core.storage import private_storage, private_upload_path
from apps.core.validators import validate_upload


class DocumentCategory(TenantModel, ActiveStatusMixin):
    """Categoria de documento (exame, laudo, termo, receita, administrativo)."""

    name = models.CharField("nome", max_length=80)
    description = models.CharField("descricao", max_length=200, blank=True)
    is_clinical = models.BooleanField(
        "conteudo clinico",
        default=True,
        help_text="Documentos clinicos exigem permissao assistencial para leitura.",
    )
    visible_to_patient_default = models.BooleanField(
        "visivel ao paciente por padrao", default=False
    )

    class Meta:
        verbose_name = "categoria de documento"
        verbose_name_plural = "categorias de documento"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_document_category_per_clinic",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Document(TenantModel):
    """
    Arquivo anexado a um paciente, atendimento ou exame.

    O arquivo fica em ``PRIVATE_MEDIA_ROOT`` (fora de qualquer diretorio
    publico) e so pode ser obtido pela view de download, que confere
    permissao, tenant e registra a auditoria.
    """

    patient = models.ForeignKey(
        "patients.Patient",
        verbose_name="paciente",
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        DocumentCategory,
        verbose_name="categoria",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    record_entry = models.ForeignKey(
        "medical_records.MedicalRecordEntry",
        verbose_name="atendimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        verbose_name="agendamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )

    title = models.CharField("titulo", max_length=180)
    description = models.TextField("descricao", blank=True)
    file = models.FileField(
        "arquivo",
        upload_to=private_upload_path,
        storage=private_storage,
        validators=[validate_upload],
    )
    original_name = models.CharField("nome original", max_length=180, blank=True, editable=False)
    content_type = models.CharField("tipo MIME", max_length=100, blank=True, editable=False)
    size = models.PositiveBigIntegerField("tamanho (bytes)", default=0, editable=False)
    checksum = models.CharField("SHA-256", max_length=64, blank=True, editable=False)

    is_sensitive = models.BooleanField("dado sensivel de saude", default=True)
    visible_to_patient = models.BooleanField("liberado no portal do paciente", default=False)
    requires_consent = models.BooleanField("exige consentimento registrado", default=False)
    issued_at = models.DateField("data do documento", null=True, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="enviado por",
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_documents",
    )
    download_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        verbose_name = "documento"
        verbose_name_plural = "documentos"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "-created_at"]),
            models.Index(fields=["patient", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if self.file and not self.checksum:
            self.original_name = (getattr(self.file, "name", "") or "")[-180:]
            self.size = getattr(self.file, "size", 0) or 0
            self.content_type = getattr(self.file.file, "content_type", "")[:100] if hasattr(
                self.file, "file"
            ) else ""
            self.checksum = self._compute_checksum()
        return super().save(*args, **kwargs)

    def _compute_checksum(self) -> str:
        digest = hashlib.sha256()
        try:
            position = self.file.tell()
            self.file.seek(0)
            for chunk in self.file.chunks():
                digest.update(chunk)
            self.file.seek(position)
        except (ValueError, OSError):  # pragma: no cover
            return ""
        return digest.hexdigest()

    @property
    def extension(self) -> str:
        return (self.original_name or self.file.name or "").rsplit(".", 1)[-1].lower()

    @property
    def is_image(self) -> bool:
        return self.extension in {"jpg", "jpeg", "png", "webp"}

    @property
    def human_size(self) -> str:
        from apps.core.utils import humanize_bytes

        return humanize_bytes(self.size)


class DocumentAccessLog(TenantModel):
    """
    Registro dedicado de acessos a documentos.

    Complementa a auditoria geral, facilitando o atendimento a pedidos de
    prestacao de contas previstos na LGPD.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="access_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    ip_address = models.CharField(max_length=45, blank=True)
    action = models.CharField(
        max_length=20,
        choices=[("view", "Visualizacao"), ("download", "Download")],
        default="download",
    )

    class Meta:
        verbose_name = "acesso a documento"
        verbose_name_plural = "acessos a documentos"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} -> {self.document}"
