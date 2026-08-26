from django.urls import path

from apps.platform_admin import views

app_name = "platform"

urlpatterns = [
    path("", views.PlatformDashboardView.as_view(), name="dashboard"),
    # Clinicas
    path("clinicas/", views.ClinicListView.as_view(), name="clinic-list"),
    path("clinicas/nova/", views.ClinicCreateView.as_view(), name="clinic-create"),
    path("clinicas/<uuid:pk>/", views.ClinicDetailView.as_view(), name="clinic-detail"),
    path("clinicas/<uuid:pk>/editar/", views.ClinicUpdateView.as_view(), name="clinic-update"),
    path(
        "clinicas/<uuid:pk>/status/<str:status>/",
        views.ClinicStatusView.as_view(),
        name="clinic-status",
    ),
    path(
        "clinicas/<uuid:pk>/acessar/",
        views.ClinicImpersonateView.as_view(),
        name="clinic-impersonate",
    ),
    # Usuarios
    path("usuarios/", views.PlatformUserListView.as_view(), name="user-list"),
    path("usuarios/<uuid:pk>/alternar/", views.PlatformUserToggleView.as_view(), name="user-toggle"),
    path(
        "usuarios/<uuid:pk>/senha/",
        views.PlatformUserPasswordResetView.as_view(),
        name="user-password-reset",
    ),
    # Seguranca e auditoria
    path("auditoria/", views.PlatformAuditView.as_view(), name="audit"),
    path("seguranca/", views.SecurityOverviewView.as_view(), name="security"),
    # Planos e assinaturas
    path("planos/", views.PlanListView.as_view(), name="plan-list"),
    path("planos/novo/", views.PlanCreateView.as_view(), name="plan-create"),
    path("planos/<uuid:pk>/editar/", views.PlanUpdateView.as_view(), name="plan-update"),
    path("assinaturas/", views.SubscriptionListView.as_view(), name="subscription-list"),
    path("organizacoes/", views.OrganizationListView.as_view(), name="organization-list"),
    # Financeiro do sistema
    path("financeiro/", views.FinanceDashboardView.as_view(), name="finance-dashboard"),
    path("financeiro/despesas/", views.SystemExpenseListView.as_view(), name="system-expense-list"),
    path(
        "financeiro/despesas/nova/",
        views.SystemExpenseCreateView.as_view(),
        name="system-expense-create",
    ),
    path(
        "financeiro/despesas/<uuid:pk>/editar/",
        views.SystemExpenseUpdateView.as_view(),
        name="system-expense-update",
    ),
]
