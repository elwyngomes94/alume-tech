from django.urls import path

from apps.patients import views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("novo/", views.PatientCreateView.as_view(), name="create"),
    path("buscar/", views.PatientSearchView.as_view(), name="search"),
    path("<uuid:pk>/", views.PatientDetailView.as_view(), name="detail"),
    path("<uuid:pk>/editar/", views.PatientUpdateView.as_view(), name="update"),
    path("<uuid:pk>/excluir/", views.PatientDeleteView.as_view(), name="delete"),
    path("<uuid:pk>/exportar/", views.PatientExportView.as_view(), name="export"),
]
