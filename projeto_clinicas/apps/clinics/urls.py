from django.urls import path

from apps.clinics import views

app_name = "clinics"

urlpatterns = [
    path("dados/", views.ClinicProfileView.as_view(), name="profile"),
    path("configuracoes/", views.ClinicSettingsView.as_view(), name="settings"),
    path("cadastros/", views.CatalogHomeView.as_view(), name="catalog"),
    path("plano/", views.BillingView.as_view(), name="billing"),
    # Especialidades
    path("especialidades/nova/", views.SpecialtyCreateView.as_view(), name="specialty-create"),
    path(
        "especialidades/<uuid:pk>/editar/",
        views.SpecialtyUpdateView.as_view(),
        name="specialty-update",
    ),
    # Servicos
    path("servicos/novo/", views.ServiceCreateView.as_view(), name="service-create"),
    path("servicos/<uuid:pk>/editar/", views.ServiceUpdateView.as_view(), name="service-update"),
    # Salas
    path("salas/nova/", views.RoomCreateView.as_view(), name="room-create"),
    path("salas/<uuid:pk>/editar/", views.RoomUpdateView.as_view(), name="room-update"),
    # Convenios
    path("convenios/novo/", views.InsuranceCreateView.as_view(), name="insurance-create"),
    path(
        "convenios/<uuid:pk>/editar/",
        views.InsuranceUpdateView.as_view(),
        name="insurance-update",
    ),
    path(
        "cadastros/<str:entity>/<uuid:pk>/excluir/",
        views.CatalogDeleteView.as_view(),
        name="catalog-delete",
    ),
]
