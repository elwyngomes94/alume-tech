from django.urls import path

from apps.medical_records import views

app_name = "medical_records"

urlpatterns = [
    path("paciente/<uuid:patient_id>/", views.RecordDetailView.as_view(), name="record-detail"),
    path("paciente/<uuid:patient_id>/pdf/", views.RecordExportPDFView.as_view(), name="record-pdf"),
    path(
        "paciente/<uuid:patient_id>/imprimir/",
        views.RecordPrintAckView.as_view(),
        name="record-print-ack",
    ),
    path(
        "paciente/<uuid:patient_id>/atendimento/novo/",
        views.RecordEntryCreateView.as_view(),
        name="entry-create",
    ),
    path("atendimento/<uuid:pk>/", views.RecordEntryDetailView.as_view(), name="entry-detail"),
    path(
        "atendimento/<uuid:pk>/editar/",
        views.RecordEntryUpdateView.as_view(),
        name="entry-update",
    ),
    path(
        "atendimento/<uuid:pk>/assinar/",
        views.RecordEntrySignView.as_view(),
        name="entry-sign",
    ),
    path(
        "atendimento/<uuid:entry_id>/prescricao/nova/",
        views.PrescriptionCreateView.as_view(),
        name="prescription-create",
    ),
    path(
        "prescricao/<uuid:pk>/",
        views.PrescriptionDetailView.as_view(),
        name="prescription-detail",
    ),
    path("modelos/", views.RecordTemplateListView.as_view(), name="template-list"),
    path("modelos/novo/", views.RecordTemplateCreateView.as_view(), name="template-create"),
    path(
        "modelos/<uuid:pk>/editar/",
        views.RecordTemplateUpdateView.as_view(),
        name="template-update",
    ),
    path("modelos/padrao/", views.RecordTemplateSeedView.as_view(), name="template-seed"),
    path("cid/buscar/", views.CIDSearchView.as_view(), name="cid-search"),
]
