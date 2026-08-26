from django.urls import path

from apps.examinations import views

app_name = "examinations"

urlpatterns = [
    path("", views.ExaminationRequestListView.as_view(), name="request-list"),
    path("nova/", views.ExaminationRequestCreateView.as_view(), name="request-create"),
    path("<uuid:pk>/", views.ExaminationRequestDetailView.as_view(), name="request-detail"),
    path("<uuid:pk>/imprimir/", views.ExaminationRequestPrintView.as_view(), name="request-print"),
    path("<uuid:pk>/resultado/", views.ExaminationResultCreateView.as_view(), name="result-create"),
    path(
        "<uuid:pk>/status/<str:status>/",
        views.ExaminationRequestStatusView.as_view(),
        name="request-status",
    ),
    path("catalogo/", views.ExaminationCatalogListView.as_view(), name="catalog-list"),
    path("catalogo/novo/", views.ExaminationCatalogCreateView.as_view(), name="catalog-create"),
]
