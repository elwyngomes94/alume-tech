from django.urls import path

from apps.automation import views

app_name = "automation"

urlpatterns = [
    path("configuracoes/", views.AutomationSettingsView.as_view(), name="settings"),
    path(
        "configuracoes/webhook/regenerar/",
        views.RegenerateWebhookSecretView.as_view(),
        name="webhook-secret-regenerate",
    ),
    path("historico/", views.AutomationExecutionListView.as_view(), name="execution-list"),
    path(
        "webhook/financeiro/<uuid:clinic_id>/",
        views.FinancialWebhookView.as_view(),
        name="financial-webhook",
    ),
]
