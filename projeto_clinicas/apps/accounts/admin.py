from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import ApiToken, LoginAttempt, Role, User, UserSession


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "role", "is_active", "mfa_enabled", "is_staff"]
    list_filter = ["role", "is_active", "mfa_enabled"]
    search_fields = ["email", "full_name", "cpf"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados pessoais", {"fields": ("full_name", "cpf", "phone", "birth_date", "avatar")}),
        ("Perfil", {"fields": ("role", "must_change_password")}),
        ("Seguranca", {"fields": ("mfa_enabled", "locked_until", "failed_login_count")}),
        (
            "Permissoes",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Datas", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "password1", "password2")}),
    )
    readonly_fields = ["created_at", "last_login"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "clinic", "base_role", "is_active"]
    list_filter = ["base_role", "is_active"]
    search_fields = ["name"]


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ["email", "successful", "ip_address", "created_at"]
    list_filter = ["successful"]
    search_fields = ["email", "ip_address"]
    readonly_fields = [f.name for f in LoginAttempt._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ["user", "ip_address", "created_at", "last_activity", "revoked_at"]
    search_fields = ["user__email", "ip_address"]


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "clinic", "prefix", "expires_at", "revoked_at"]
    readonly_fields = ["key_hash", "prefix"]
