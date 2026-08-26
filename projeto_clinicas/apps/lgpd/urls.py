from django.urls import path

from apps.lgpd import views

app_name = "lgpd"

urlpatterns = [
    path("", views.LgpdDashboardView.as_view(), name="dashboard"),
    path("termos/", views.ConsentTypeListView.as_view(), name="consent-type-list"),
    path("termos/novo/", views.ConsentTypeCreateView.as_view(), name="consent-type-create"),
    path(
        "termos/<uuid:pk>/editar/",
        views.ConsentTypeUpdateView.as_view(),
        name="consent-type-update",
    ),
    path("consentimentos/", views.ConsentListView.as_view(), name="consent-list"),
    path("consentimentos/novo/", views.ConsentCreateView.as_view(), name="consent-create"),
    path(
        "consentimentos/<uuid:pk>/revogar/",
        views.ConsentRevokeView.as_view(),
        name="consent-revoke",
    ),
    path("solicitacoes/", views.DataRequestListView.as_view(), name="request-list"),
    path("solicitacoes/nova/", views.DataRequestCreateView.as_view(), name="request-create"),
    path("solicitacoes/<uuid:pk>/", views.DataRequestDetailView.as_view(), name="request-detail"),
    path(
        "solicitacoes/<uuid:pk>/resolver/",
        views.DataRequestResolveView.as_view(),
        name="request-resolve",
    ),
    path("paciente/<uuid:pk>/anonimizar/", views.PatientAnonymizeView.as_view(), name="anonymize"),
    path("incidentes/", views.IncidentListView.as_view(), name="incident-list"),
    path("incidentes/novo/", views.IncidentCreateView.as_view(), name="incident-create"),
]
