"""Rotas da API v1 (/api/v1/)."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.api import views

router = DefaultRouter()
router.register("clinicas", views.ClinicViewSet, basename="clinica")
router.register("especialidades", views.SpecialtyViewSet, basename="especialidade")
router.register("servicos", views.ServiceViewSet, basename="servico")
router.register("salas", views.RoomViewSet, basename="sala")
router.register("convenios", views.InsuranceViewSet, basename="convenio")
router.register("profissionais", views.ProfessionalViewSet, basename="profissional")
router.register("pacientes", views.PatientViewSet, basename="paciente")
router.register("agendamentos", views.AppointmentViewSet, basename="agendamento")
router.register("prontuarios", views.MedicalRecordEntryViewSet, basename="prontuario")
router.register("exames", views.ExaminationRequestViewSet, basename="exame")
router.register("documentos", views.DocumentViewSet, basename="documento")
router.register("notificacoes", views.NotificationViewSet, basename="notificacao")

app_name = "api"

urlpatterns = [
    path("eu/", views.MeView.as_view(), name="me"),
    path("", include(router.urls)),
]
