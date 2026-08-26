"""
Viewsets da API v1.

Todo recurso da clinica passa por :class:`TenantScopedViewSet`, que:

1. usa o manager com filtro automatico por tenant;
2. reforca o filtro pela clinica da requisicao (defesa em profundidade);
3. exige a permissao declarada em ``permission_map``;
4. registra auditoria de leitura de dados sensiveis.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.permissions import ClinicPermission, HasClinicContext
from apps.api.serializers import (
    AppointmentSerializer,
    ClinicSerializer,
    DocumentSerializer,
    ExaminationRequestSerializer,
    InsurancePlanSerializer,
    MedicalRecordEntrySerializer,
    NotificationSerializer,
    PatientListSerializer,
    PatientSerializer,
    ProfessionalSerializer,
    RoomSerializer,
    ServiceSerializer,
    SpecialtySerializer,
)
from apps.audit.services import log_view
from apps.clinics.models import Clinic, InsurancePlan, Room, Service, Specialty
from apps.documents.models import Document
from apps.examinations.models import ExaminationRequest
from apps.medical_records.models import MedicalRecordEntry
from apps.medical_records.services import can_access_patient_record
from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.professionals.models import Professional
from apps.scheduling.models import Appointment


class TenantScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasClinicContext, ClinicPermission]
    audit_retrieve = False

    def get_queryset(self):
        queryset = super().get_queryset()
        clinic = getattr(self.request, "clinic", None)
        if clinic is None:
            return queryset.none()
        if hasattr(queryset.model, "clinic_id"):
            queryset = queryset.filter(clinic_id=clinic.pk)
        return queryset

    def perform_destroy(self, instance):
        """Exclusao logica com registro de quem excluiu."""
        instance.delete(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if self.audit_retrieve:
            log_view(self.get_object(), request=request, description="Consulta via API")
        return response


class SpecialtyViewSet(TenantScopedViewSet):
    queryset = Specialty.objects.all()
    serializer_class = SpecialtySerializer
    search_fields = ["name"]
    ordering_fields = ["name"]
    permission_map = {"read": "clinic.view", "write": "specialty.manage"}


class ServiceViewSet(TenantScopedViewSet):
    queryset = Service.objects.select_related("specialty")
    serializer_class = ServiceSerializer
    search_fields = ["name", "code"]
    filterset_fields = ["specialty", "is_active"]
    permission_map = {"read": "clinic.view", "write": "service.manage"}


class RoomViewSet(TenantScopedViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    permission_map = {"read": "clinic.view", "write": "room.manage"}


class InsuranceViewSet(TenantScopedViewSet):
    queryset = InsurancePlan.objects.all()
    serializer_class = InsurancePlanSerializer
    permission_map = {"read": "clinic.view", "write": "insurance.manage"}


class ProfessionalViewSet(TenantScopedViewSet):
    queryset = Professional.objects.prefetch_related("specialties")
    serializer_class = ProfessionalSerializer
    search_fields = ["full_name", "registry_number"]
    filterset_fields = ["is_active", "specialties"]
    permission_map = {
        "read": "professional.view",
        "create": "professional.add",
        "update": "professional.change",
        "partial_update": "professional.change",
        "destroy": "professional.delete",
    }

    @action(detail=True, methods=["get"], url_path="horarios")
    def slots(self, request, pk=None):
        """Horarios livres do profissional em uma data."""
        from apps.core.utils import parse_date
        from apps.scheduling.services import day_slots

        professional = self.get_object()
        day = parse_date(request.query_params.get("data", "")) or timezone.localdate()
        return Response(
            {
                "data": day.isoformat(),
                "horarios": [
                    {
                        "inicio": timezone.localtime(slot.start).strftime("%H:%M"),
                        "fim": timezone.localtime(slot.end).strftime("%H:%M"),
                        "disponivel": slot.available,
                        "motivo": slot.reason,
                    }
                    for slot in day_slots(professional, day)
                ],
            }
        )


class PatientViewSet(TenantScopedViewSet):
    queryset = Patient.objects.select_related("insurance")
    search_fields = ["full_name", "social_name", "cpf", "email", "mobile"]
    filterset_fields = ["status", "insurance"]
    ordering_fields = ["full_name", "created_at"]
    audit_retrieve = True
    permission_map = {
        "read": "patient.view",
        "create": "patient.add",
        "update": "patient.change",
        "partial_update": "patient.change",
        "destroy": "patient.delete",
    }

    def get_serializer_class(self):
        if self.action == "list":
            return PatientListSerializer
        return PatientSerializer


class AppointmentViewSet(TenantScopedViewSet):
    queryset = Appointment.objects.select_related("patient", "professional", "service", "room")
    serializer_class = AppointmentSerializer
    filterset_fields = ["status", "professional", "patient"]
    ordering_fields = ["start_at"]
    permission_map = {
        "read": "appointment.view",
        "create": "appointment.add",
        "update": "appointment.change",
        "partial_update": "appointment.change",
        "destroy": "appointment.cancel",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        clinic = getattr(self.request, "clinic", None)
        if clinic is not None and not user.has_clinic_perm("appointment.view_all", clinic):
            queryset = queryset.filter(professional__user=user)
        start = self.request.query_params.get("inicio")
        end = self.request.query_params.get("fim")
        if start:
            queryset = queryset.filter(start_at__date__gte=start)
        if end:
            queryset = queryset.filter(start_at__date__lte=end)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, origin=Appointment.Origin.API)

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        from django.core.exceptions import ValidationError

        from apps.scheduling.services import change_status

        appointment = self.get_object()
        new_status = request.data.get("status", "")
        try:
            change_status(
                appointment, new_status, user=request.user, reason=request.data.get("motivo", "")
            )
        except ValidationError as exc:
            return Response({"erro": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(appointment).data)


class MedicalRecordEntryViewSet(TenantScopedViewSet):
    queryset = MedicalRecordEntry.objects.select_related("record__patient", "professional")
    serializer_class = MedicalRecordEntrySerializer
    filterset_fields = ["professional", "is_draft"]
    audit_retrieve = True
    permission_map = {
        "read": "medicalrecord.view",
        "create": "medicalrecord.add",
        "update": "medicalrecord.change",
        "partial_update": "medicalrecord.change",
        "destroy": "medicalrecord.change",
    }

    def get_queryset(self):
        """Profissional so acessa prontuarios com vinculo assistencial."""
        queryset = super().get_queryset()
        user = self.request.user
        clinic = getattr(self.request, "clinic", None)
        if clinic is None or user.is_superadmin:
            return queryset
        from apps.accounts.permissions import Roles

        if user.role_in(clinic) == Roles.CLINIC_ADMIN:
            return queryset
        return queryset.filter(
            Q(professional__user=user) | Q(record__patient__appointments__professional__user=user)
        ).distinct()


class ExaminationRequestViewSet(TenantScopedViewSet):
    queryset = ExaminationRequest.objects.select_related("patient", "professional").prefetch_related(
        "items"
    )
    serializer_class = ExaminationRequestSerializer
    filterset_fields = ["status", "priority", "patient", "professional"]
    audit_retrieve = True
    permission_map = {
        "read": "examination.view",
        "create": "examination.request",
        "update": "examination.result",
        "partial_update": "examination.result",
        "destroy": "examination.request",
    }


class DocumentViewSet(TenantScopedViewSet):
    queryset = Document.objects.select_related("patient", "category")
    serializer_class = DocumentSerializer
    filterset_fields = ["patient", "category", "visible_to_patient"]
    audit_retrieve = True
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_map = {
        "read": "document.view",
        "create": "document.add",
        "update": "document.change",
        "partial_update": "document.add",
        "destroy": "document.delete",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        clinic = getattr(self.request, "clinic", None)
        if clinic is None:
            return queryset.none()
        from apps.accounts.permissions import Roles

        role = user.role_in(clinic)
        if role == Roles.PROFESSIONAL:
            allowed = [
                document.pk
                for document in queryset
                if document.patient_id is None
                or can_access_patient_record(user, clinic, document.patient)
            ]
            queryset = queryset.filter(pk__in=allowed)
        elif role == Roles.RECEPTIONIST:
            queryset = queryset.filter(is_sensitive=False)
        return queryset

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class ClinicViewSet(viewsets.ReadOnlyModelViewSet):
    """Clinicas acessiveis ao usuario autenticado."""

    serializer_class = ClinicSerializer
    permission_classes = [IsAuthenticated]
    requires_clinic = False

    def get_queryset(self):
        return self.request.user.accessible_clinics()


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    requires_clinic = False

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="ler")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_as_read()
        return Response(self.get_serializer(notification).data)


class MeView(APIView):
    """Identidade, clinica ativa e permissoes efetivas do usuario."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        clinic = getattr(request, "clinic", None)
        return Response(
            {
                "id": str(request.user.pk),
                "nome": request.user.full_name,
                "email": request.user.email,
                "perfil": request.user.role,
                "superadmin": request.user.is_superadmin,
                "clinica_ativa": (
                    {"id": str(clinic.pk), "nome": str(clinic), "slug": clinic.slug}
                    if clinic
                    else None
                ),
                "permissoes": sorted(request.user.clinic_permissions(clinic)) if clinic else [],
                "clinicas": [
                    {"id": str(item.pk), "nome": str(item)}
                    for item in request.user.accessible_clinics()[:50]
                ],
            }
        )
