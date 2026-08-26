from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportHomeView.as_view(), name="home"),
    path("<str:report>/", views.ReportDetailView.as_view(), name="detail"),
    path("<str:report>/exportar/<str:fmt>/", views.ReportExportView.as_view(), name="export"),
]
