from django.urls import path

from apps.portal import views

app_name = "portal"

urlpatterns = [
    path("", views.PortalHomeView.as_view(), name="home"),
    path("sem-cadastro/", views.PortalNoRecordView.as_view(), name="no-record"),
    path("perfil/", views.PortalProfileView.as_view(), name="profile"),
    path("agendamentos/", views.PortalAppointmentListView.as_view(), name="appointments"),
    path(
        "agendamentos/solicitar/",
        views.PortalAppointmentRequestView.as_view(),
        name="appointment-request",
    ),
    path(
        "agendamentos/<uuid:pk>/cancelar/",
        views.PortalAppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
    path("documentos/", views.PortalDocumentListView.as_view(), name="documents"),
    path(
        "documentos/<uuid:pk>/baixar/",
        views.PortalDocumentDownloadView.as_view(),
        name="document-download",
    ),
    path("exames/", views.PortalExaminationListView.as_view(), name="examinations"),
    path("prescricoes/", views.PortalPrescriptionListView.as_view(), name="prescriptions"),
    path(
        "prescricoes/<uuid:pk>/",
        views.PortalPrescriptionDetailView.as_view(),
        name="prescription-detail",
    ),
    path("historico/", views.PortalHistoryView.as_view(), name="history"),
    path("meus-dados/", views.PortalDataExportView.as_view(), name="data-export"),
]
