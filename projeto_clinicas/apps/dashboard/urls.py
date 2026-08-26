from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardHomeView.as_view(), name="home"),
    path("clinica/", views.ClinicDashboardView.as_view(), name="clinic"),
    path("profissional/", views.ProfessionalDashboardView.as_view(), name="professional"),
    path("recepcao/", views.ReceptionDashboardView.as_view(), name="reception"),
    path("busca/", views.GlobalSearchView.as_view(), name="search"),
]
