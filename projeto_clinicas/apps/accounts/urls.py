from django.contrib.auth import views as auth_views
from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    # Autenticacao
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("mfa/verificar/", views.MFAVerifyView.as_view(), name="mfa-verify"),
    path("mfa/ativar/", views.MFASetupView.as_view(), name="mfa-setup"),
    path("mfa/desativar/", views.MFADisableView.as_view(), name="mfa-disable"),
    # Senha
    path("trocar-senha/", views.PasswordChangeView.as_view(), name="password-change"),
    path("senha/recuperar/", views.PasswordResetView.as_view(), name="password-reset"),
    path(
        "senha/recuperar/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password-reset-done",
    ),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    # Conta
    path("perfil/", views.ProfileView.as_view(), name="profile"),
    path("seguranca/", views.SecurityView.as_view(), name="security"),
    path("seguranca/sessao/<uuid:pk>/revogar/", views.SessionRevokeView.as_view(), name="session-revoke"),
    path("seguranca/token/novo/", views.ApiTokenCreateView.as_view(), name="token-create"),
    path("seguranca/token/<uuid:pk>/revogar/", views.ApiTokenRevokeView.as_view(), name="token-revoke"),
    path("clinica/<uuid:pk>/ativar/", views.ClinicSwitchView.as_view(), name="clinic-switch"),
    path("sem-clinica/", views.NoClinicView.as_view(), name="no-clinic"),
    # Gestao de usuarios da clinica
    path("usuarios/", views.ClinicUserListView.as_view(), name="user-list"),
    path("usuarios/novo/", views.ClinicUserCreateView.as_view(), name="user-create"),
    path("usuarios/<uuid:pk>/editar/", views.ClinicUserUpdateView.as_view(), name="user-update"),
    path("usuarios/<uuid:pk>/remover/", views.ClinicUserRemoveView.as_view(), name="user-remove"),
    path(
        "usuarios/<uuid:pk>/senha/",
        views.ClinicUserPasswordResetView.as_view(),
        name="user-password-reset",
    ),
    path(
        "usuarios/<uuid:pk>/permissoes/",
        views.MembershipPermissionsView.as_view(),
        name="membership-permissions",
    ),
    # Papeis personalizados
    path("papeis/", views.RoleListView.as_view(), name="role-list"),
    path("papeis/novo/", views.RoleCreateView.as_view(), name="role-create"),
    path("papeis/<uuid:pk>/editar/", views.RoleUpdateView.as_view(), name="role-update"),
    path("papeis/<uuid:pk>/excluir/", views.RoleDeleteView.as_view(), name="role-delete"),
]
