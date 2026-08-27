"""
Mapa de URLs do JJA System.

    /                 -> redireciona conforme o perfil autenticado
    /accounts/        -> autenticacao, MFA, sessoes, senha
    /app/             -> painel operacional da clinica ativa
    /platform/        -> administracao global (SUPERADMIN)
    /patient/         -> portal do paciente
    /api/v1/          -> API REST versionada
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path("", core_views.RootRedirectView.as_view(), name="root"),
    path("healthz/", core_views.health_check, name="health-check"),
    path("app/cep/<str:cep>/", core_views.cep_lookup, name="cep-lookup"),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("app/", include("apps.dashboard.urls", namespace="dashboard")),
    path("app/clinica/", include("apps.clinics.urls", namespace="clinics")),
    path("app/pacientes/", include("apps.patients.urls", namespace="patients")),
    path("app/profissionais/", include("apps.professionals.urls", namespace="professionals")),
    path("app/agenda/", include("apps.scheduling.urls", namespace="scheduling")),
    path("app/prontuarios/", include("apps.medical_records.urls", namespace="medical_records")),
    path("app/exames/", include("apps.examinations.urls", namespace="examinations")),
    path("app/documentos/", include("apps.documents.urls", namespace="documents")),
    path("app/financeiro/", include("apps.finance.urls", namespace="finance")),
    path("app/estoque/", include("apps.inventory.urls", namespace="inventory")),
    path("app/automacoes/", include("apps.automation.urls", namespace="automation")),
    path("app/notificacoes/", include("apps.notifications.urls", namespace="notifications")),
    path("app/relatorios/", include("apps.reports.urls", namespace="reports")),
    path("app/lgpd/", include("apps.lgpd.urls", namespace="lgpd")),
    path("app/auditoria/", include("apps.audit.urls", namespace="audit")),
    path("platform/", include("apps.platform_admin.urls", namespace="platform")),
    path("patient/", include("apps.portal.urls", namespace="portal")),
    path("api/v1/", include(("apps.api.urls", "api"), namespace="v1")),
    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.handler403"
handler404 = "apps.core.views.handler404"
handler500 = "apps.core.views.handler500"
