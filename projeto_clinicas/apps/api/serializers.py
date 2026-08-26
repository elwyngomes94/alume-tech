"""Serializers da API v1."""
from __future__ import annotations

from rest_framework import serializers

from apps.clinics.models import Clinic, InsurancePlan, Room, Service, Specialty
from apps.documents.models import Document
from apps.examinations.models import ExaminationRequest, ExaminationRequestItem
from apps.medical_records.models import MedicalRecordEntry
from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.professionals.models import Professional
from apps.scheduling.models import Appointment


class TenantScopedSerializer(serializers.ModelSerializer):
    """
    Base dos serializers de recursos da clinica.

    O campo ``clinic`` nunca e aceito na entrada: a clinica vem do contexto da
    requisicao, impedindo que um cliente grave dados em outro tenant.
    """

    def create(self, validated_data):
        validated_data.pop("clinic", None)
        request = self.context.get("request")
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            raise serializers.ValidationError("Clinica ativa nao identificada.")
        validated_data["clinic"] = clinic
        return super().create(validated_data)


class ClinicSerializer(serializers.ModelSerializer):
    clinic_type_display = serializers.CharField(source="get_clinic_type_display", read_only=True)

    class Meta:
        model = Clinic
        fields = [
            "id",
            "trade_name",
            "legal_name",
            "slug",
            "clinic_type",
            "clinic_type_display",
            "city",
            "state",
            "phone",
            "email",
            "status",
        ]
        read_only_fields = fields


class SpecialtySerializer(TenantScopedSerializer):
    class Meta:
        model = Specialty
        fields = ["id", "name", "description", "color", "is_active"]


class ServiceSerializer(TenantScopedSerializer):
    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "code",
            "specialty",
            "duration_minutes",
            "price",
            "requires_room",
            "is_active",
        ]


class RoomSerializer(TenantScopedSerializer):
    class Meta:
        model = Room
        fields = ["id", "name", "identifier", "capacity", "is_active"]


class InsurancePlanSerializer(TenantScopedSerializer):
    class Meta:
        model = InsurancePlan
        fields = ["id", "name", "registry_code", "is_active"]


class ProfessionalSerializer(TenantScopedSerializer):
    specialties_names = serializers.SerializerMethodField()
    registry = serializers.CharField(source="registry_label", read_only=True)

    class Meta:
        model = Professional
        fields = [
            "id",
            "full_name",
            "social_name",
            "email",
            "phone",
            "council",
            "registry_number",
            "registry_state",
            "registry",
            "specialties",
            "specialties_names",
            "appointment_duration",
            "accepts_online_scheduling",
            "is_active",
        ]

    def get_specialties_names(self, obj) -> list:
        return [specialty.name for specialty in obj.specialties.all()]


class PatientListSerializer(TenantScopedSerializer):
    """Listagem com minimizacao de dados (CPF mascarado)."""

    display_name = serializers.CharField(read_only=True)
    cpf = serializers.CharField(source="masked_cpf", read_only=True)
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id",
            "record_number",
            "display_name",
            "cpf",
            "age",
            "mobile",
            "email",
            "status",
        ]


class PatientSerializer(TenantScopedSerializer):
    display_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id",
            "record_number",
            "full_name",
            "social_name",
            "display_name",
            "cpf",
            "rg",
            "birth_date",
            "age",
            "gender",
            "email",
            "phone",
            "mobile",
            "whatsapp",
            "blood_type",
            "allergies",
            "chronic_conditions",
            "continuous_medications",
            "insurance",
            "insurance_number",
            "status",
        ]
        read_only_fields = ["record_number"]


class AppointmentSerializer(TenantScopedSerializer):
    patient_name = serializers.CharField(source="patient.display_name", read_only=True)
    professional_name = serializers.CharField(
        source="professional.display_name", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_name",
            "professional",
            "professional_name",
            "service",
            "room",
            "insurance",
            "start_at",
            "end_at",
            "status",
            "status_display",
            "origin",
            "is_overbooking",
            "duration_minutes",
            "notes",
        ]
        read_only_fields = ["origin"]

    def validate(self, attrs):
        start = attrs.get("start_at") or getattr(self.instance, "start_at", None)
        end = attrs.get("end_at") or getattr(self.instance, "end_at", None)
        if start and end and start >= end:
            raise serializers.ValidationError({"end_at": "Termino deve ser apos o inicio."})

        request = self.context.get("request")
        clinic = getattr(request, "clinic", None)
        for field in ("patient", "professional", "service", "room", "insurance"):
            value = attrs.get(field)
            if value is not None and getattr(value, "clinic_id", None) != getattr(
                clinic, "pk", None
            ):
                raise serializers.ValidationError(
                    {field: "Registro nao pertence a clinica ativa."}
                )
        return attrs


class ExaminationItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExaminationRequestItem
        fields = ["id", "name", "quantity", "notes"]


class ExaminationRequestSerializer(TenantScopedSerializer):
    items = ExaminationItemSerializer(many=True, read_only=True)
    patient_name = serializers.CharField(source="patient.display_name", read_only=True)

    class Meta:
        model = ExaminationRequest
        fields = [
            "id",
            "number",
            "patient",
            "patient_name",
            "professional",
            "clinical_indication",
            "priority",
            "status",
            "requested_at",
            "released_to_patient",
            "items",
        ]
        read_only_fields = ["number"]


class MedicalRecordEntrySerializer(TenantScopedSerializer):
    patient_name = serializers.CharField(source="record.patient.display_name", read_only=True)
    professional_name = serializers.CharField(
        source="professional.display_name", read_only=True
    )

    class Meta:
        model = MedicalRecordEntry
        fields = [
            "id",
            "record",
            "patient_name",
            "professional",
            "professional_name",
            "template",
            "title",
            "data",
            "attended_at",
            "is_draft",
            "signed_at",
            "version",
        ]
        read_only_fields = ["signed_at", "version"]


class DocumentSerializer(TenantScopedSerializer):
    download_url = serializers.SerializerMethodField()
    human_size = serializers.CharField(read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "patient",
            "category",
            "title",
            "description",
            "issued_at",
            "is_sensitive",
            "visible_to_patient",
            "human_size",
            "download_url",
            "created_at",
        ]
        read_only_fields = ["human_size", "created_at"]

    def get_download_url(self, obj) -> str:
        from django.urls import reverse

        return reverse("documents:download", args=[obj.pk])


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "message", "event", "level", "url", "read_at", "created_at"]
        read_only_fields = fields
