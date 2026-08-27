"""Views de autenticacao, seguranca da conta e gestao de usuarios da clinica."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.accounts import mfa
from apps.accounts.backends import AccountLocked, ThrottledAuthentication
from apps.accounts.forms import (
    AdminSetPasswordForm,
    ApiTokenForm,
    ClinicUserForm,
    JJAPasswordChangeForm,
    JJASetPasswordForm,
    LoginForm,
    MembershipPermissionForm,
    MFASetupForm,
    MFAVerifyForm,
    ProfileForm,
    RoleForm,
)
from apps.accounts.middleware import MFA_VERIFIED_KEY
from apps.accounts.models import ApiToken, Role, User, UserSession
from apps.accounts.permissions import Roles, permissions_by_group
from apps.accounts.services import (
    DEFAULT_INITIAL_PASSWORD,
    admin_set_password,
    create_api_token,
    record_attempt,
    register_login_success,
    revoke_other_sessions,
)
from apps.audit.models import AuditAction
from apps.audit.services import log_action
from apps.core.middleware import client_ip
from apps.core.mixins import ClinicViewMixin
from apps.tenants.middleware import SESSION_CLINIC_KEY
from apps.tenants.models import ClinicMembership

MFA_PENDING_USER_KEY = "jja_mfa_pending_user"


# ---------------------------------------------------------------------------
# Autenticacao
# ---------------------------------------------------------------------------
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if user.mfa_enabled:
            # Nao autentica ainda: guarda o usuario e exige o segundo fator.
            self.request.session[MFA_PENDING_USER_KEY] = str(user.pk)
            self.request.session.set_expiry(300)
            return redirect("accounts:mfa-verify")

        auth_login(self.request, user, backend="apps.accounts.backends.EmailBackend")
        register_login_success(user, self.request)
        record_attempt(
            user.email,
            True,
            "Login realizado",
            client_ip(self.request),
            self.request.META.get("HTTP_USER_AGENT", ""),
        )
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        email = (form.data.get("username") or "")[:254]
        record_attempt(
            email,
            False,
            "Credenciais invalidas",
            client_ip(self.request),
            self.request.META.get("HTTP_USER_AGENT", ""),
        )
        return super().form_invalid(form)

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except (ThrottledAuthentication, AccountLocked) as exc:
            record_attempt(
                (request.POST.get("username") or "")[:254],
                False,
                str(exc),
                client_ip(request),
                request.META.get("HTTP_USER_AGENT", ""),
            )
            messages.error(request, str(exc))
            return redirect("accounts:login")

    def get_success_url(self):
        return self.get_redirect_url() or reverse("root")


class LogoutView(View):
    def post(self, request):
        return self._logout(request)

    def get(self, request):
        return self._logout(request)

    def _logout(self, request):
        if request.user.is_authenticated:
            log_action(AuditAction.LOGOUT, description="Logout", request=request)
            session_key = request.session.session_key
            UserSession.objects.filter(user=request.user, session_key=session_key).update(
                revoked_at=timezone.now()
            )
        auth_logout(request)
        messages.info(request, "Sessao encerrada.")
        return redirect("accounts:login")


class MFAVerifyView(FormView):
    """Segunda etapa: valida o codigo TOTP e conclui o login."""

    template_name = "accounts/mfa_verify.html"
    form_class = MFAVerifyForm

    def dispatch(self, request, *args, **kwargs):
        self.pending_user = None
        pending_id = request.session.get(MFA_PENDING_USER_KEY)
        if pending_id:
            self.pending_user = User.objects.filter(pk=pending_id, is_active=True).first()
        elif request.user.is_authenticated and request.user.mfa_enabled:
            self.pending_user = request.user
        if self.pending_user is None:
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = self.pending_user
        if not mfa.verify_code(user.mfa_secret, form.cleaned_data["code"]):
            messages.error(self.request, "Codigo invalido ou expirado.")
            record_attempt(user.email, False, "Codigo MFA invalido", client_ip(self.request))
            return self.form_invalid(form)

        if not self.request.user.is_authenticated:
            auth_login(self.request, user, backend="apps.accounts.backends.EmailBackend")
        self.request.session.pop(MFA_PENDING_USER_KEY, None)
        self.request.session[MFA_VERIFIED_KEY] = True
        self.request.session.set_expiry(0)
        register_login_success(user, self.request)
        record_attempt(user.email, True, "Login com MFA", client_ip(self.request))
        return redirect("root")


class MFASetupView(LoginRequiredMixin, FormView):
    template_name = "accounts/mfa_setup.html"
    form_class = MFASetupForm
    success_url = reverse_lazy("accounts:security")

    def get_secret(self) -> str:
        secret = self.request.session.get("jja_mfa_new_secret")
        if not secret:
            secret = mfa.generate_secret()
            self.request.session["jja_mfa_new_secret"] = secret
        return secret

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        secret = self.get_secret()
        context["secret"] = secret
        context["provisioning_uri"] = mfa.provisioning_uri(secret, self.request.user.email)
        return context

    def form_valid(self, form):
        secret = self.get_secret()
        if not mfa.verify_code(secret, form.cleaned_data["code"]):
            messages.error(self.request, "Codigo invalido. Confira o horario do dispositivo.")
            return self.form_invalid(form)
        user = self.request.user
        user.mfa_secret = secret
        user.mfa_enabled = True
        user.mfa_confirmed_at = timezone.now()
        user.save(update_fields=["mfa_secret", "mfa_enabled", "mfa_confirmed_at"])
        self.request.session.pop("jja_mfa_new_secret", None)
        self.request.session[MFA_VERIFIED_KEY] = True
        log_action(AuditAction.MFA_CHANGE, obj=user, description="MFA ativado", request=self.request)
        messages.success(self.request, "Autenticacao em dois fatores ativada.")
        return super().form_valid(form)


class MFADisableView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        user.mfa_enabled = False
        user.mfa_secret = ""
        user.mfa_confirmed_at = None
        user.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_confirmed_at"])
        log_action(AuditAction.MFA_CHANGE, obj=user, description="MFA desativado", request=request)
        messages.warning(request, "Autenticacao em dois fatores desativada.")
        return redirect("accounts:security")


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = JJAPasswordChangeForm
    success_url = reverse_lazy("accounts:security")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        user.must_change_password = False
        user.password_changed_at = timezone.now()
        user.save(update_fields=["must_change_password", "password_changed_at"])
        revoke_other_sessions(user, self.request.session.session_key or "")
        log_action(
            AuditAction.PASSWORD_CHANGE,
            obj=user,
            description="Senha alterada pelo proprio usuario",
            request=self.request,
        )
        messages.success(self.request, "Senha alterada. As demais sessoes foram encerradas.")
        return response


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/emails/password_reset.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password-reset-done")


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = JJASetPasswordForm
    success_url = reverse_lazy("accounts:login")


# ---------------------------------------------------------------------------
# Conta do usuario
# ---------------------------------------------------------------------------
class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Perfil atualizado.")
        return super().form_valid(form)


class SecurityView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/security.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sessions"] = UserSession.objects.filter(
            user=self.request.user, revoked_at__isnull=True
        )[:20]
        context["current_session_key"] = self.request.session.session_key
        context["api_tokens"] = ApiToken.objects.filter(
            user=self.request.user, revoked_at__isnull=True
        )
        context["token_form"] = ApiTokenForm()
        return context


class SessionRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(UserSession, pk=pk, user=request.user)
        session.revoke()
        log_action(
            AuditAction.SECURITY_ALERT,
            obj=session,
            description="Sessao revogada pelo usuario",
            request=request,
        )
        messages.success(request, "Sessao encerrada.")
        return redirect("accounts:security")


class ApiTokenCreateView(LoginRequiredMixin, View):
    def post(self, request):
        form = ApiTokenForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Informe uma descricao para o token.")
            return redirect("accounts:security")
        _token, raw = create_api_token(
            request.user,
            form.cleaned_data["name"],
            clinic=getattr(request, "clinic", None),
            expires_in_days=form.cleaned_data["expires_in_days"],
        )
        messages.success(
            request,
            f"Token criado. Guarde agora, ele nao sera exibido novamente: {raw}",
        )
        return redirect("accounts:security")


class ApiTokenRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        token = get_object_or_404(ApiToken, pk=pk, user=request.user)
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
        messages.success(request, "Token revogado.")
        return redirect("accounts:security")


class ClinicSwitchView(LoginRequiredMixin, View):
    """Troca a clinica ativa da sessao (sempre revalidando o vinculo)."""

    def post(self, request, pk):
        from apps.clinics.models import Clinic

        clinic = get_object_or_404(Clinic, pk=pk)
        if not request.user.can_access_clinic(clinic):
            log_action(
                AuditAction.ACCESS_DENIED,
                obj=clinic,
                description="Tentativa de ativar clinica sem vinculo",
                request=request,
                result="denied",
            )
            raise Http404
        request.session[SESSION_CLINIC_KEY] = str(clinic.pk)
        log_action(
            AuditAction.TENANT_SWITCH,
            obj=clinic,
            description=f"Clinica ativa alterada para {clinic}",
            request=request,
        )
        messages.success(request, f"Voce esta operando em {clinic}.")
        return redirect(request.POST.get("next") or "dashboard:home")


class NoClinicView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/no_clinic.html"


# ---------------------------------------------------------------------------
# Gestao de usuarios da clinica (administrador local)
# ---------------------------------------------------------------------------
class ClinicUserListView(ClinicViewMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "memberships"
    paginate_by = 25
    required_permission = "user.view"

    def get_queryset(self):
        queryset = (
            ClinicMembership.all_objects.filter(
                clinic=self.request.clinic, is_deleted=False
            )
            .select_related("user", "custom_role")
            .order_by("user__full_name")
        )
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(user__full_name__icontains=search)
        role = self.request.GET.get("role", "")
        if role:
            queryset = queryset.filter(role=role)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["roles"] = [(v, l) for v, l in Roles.CHOICES if v != Roles.SUPERADMIN]
        return context


class ClinicUserCreateView(ClinicViewMixin, CreateView):
    template_name = "accounts/user_form.html"
    form_class = ClinicUserForm
    required_permission = "user.add"
    success_url = reverse_lazy("accounts:user-list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        email = form.cleaned_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        provisional_password = None
        if user is None:
            user = form.save(commit=False)
            user.email = email
            user.role = form.cleaned_data["role"]
            provisional_password = DEFAULT_INITIAL_PASSWORD
            user.set_password(provisional_password)
            user.must_change_password = True
            user.save()
        ClinicMembership.objects.create(
            user=user,
            clinic=self.request.clinic,
            role=form.cleaned_data["role"],
            custom_role=form.cleaned_data.get("custom_role"),
            job_title=form.cleaned_data.get("job_title", ""),
        )
        if provisional_password:
            messages.success(
                self.request,
                f"Usuario criado. Senha provisoria: {provisional_password} "
                "(sera solicitada a troca no primeiro acesso).",
            )
        else:
            messages.success(self.request, "Usuario existente vinculado a esta clinica.")
        return redirect(self.success_url)


class ClinicUserUpdateView(ClinicViewMixin, UpdateView):
    template_name = "accounts/user_form.html"
    form_class = ClinicUserForm
    required_permission = "user.change"
    success_url = reverse_lazy("accounts:user-list")

    def get_object(self, queryset=None):
        membership = get_object_or_404(
            ClinicMembership.all_objects.select_related("user"),
            pk=self.kwargs["pk"],
            clinic=self.request.clinic,
            is_deleted=False,
        )
        self.membership = membership
        return membership.user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["clinic"] = self.request.clinic
        kwargs["membership"] = self.membership
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        self.membership.role = form.cleaned_data["role"]
        self.membership.custom_role = form.cleaned_data.get("custom_role")
        self.membership.job_title = form.cleaned_data.get("job_title", "")
        self.membership.save()
        messages.success(self.request, "Usuario atualizado.")
        return response


class ClinicUserRemoveView(ClinicViewMixin, View):
    required_permission = "user.delete"

    def post(self, request, pk):
        membership = get_object_or_404(
            ClinicMembership.all_objects, pk=pk, clinic=request.clinic, is_deleted=False
        )
        if membership.user_id == request.user.pk:
            messages.error(request, "Voce nao pode remover o proprio vinculo.")
            return redirect("accounts:user-list")
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        membership.delete(user=request.user)
        messages.success(request, "Vinculo removido desta clinica.")
        return redirect("accounts:user-list")


class ClinicUserPasswordResetView(ClinicViewMixin, View):
    """
    Definir/redefinir a senha de um usuario da clinica.

    Restrito a quem pode editar usuarios (``user.change``). O administrador
    da clinica nunca pode alterar a senha de um SUPERADMIN por aqui, e nao
    pode usar este atalho para a propria senha (usa a troca de senha normal,
    que exige a senha atual).
    """

    required_permission = "user.change"
    template_name = "accounts/password_admin_form.html"

    def get_membership(self):
        membership = get_object_or_404(
            ClinicMembership.all_objects.select_related("user"),
            pk=self.kwargs["pk"], clinic=self.request.clinic, is_deleted=False,
        )
        if membership.user.is_superadmin:
            raise PermissionDenied(
                "Nao e possivel alterar a senha de um administrador da plataforma por aqui."
            )
        if membership.user_id == self.request.user.pk:
            raise PermissionDenied(
                "Para alterar a propria senha, use a opcao 'Trocar senha' em Seguranca."
            )
        return membership

    def get(self, request, pk):
        membership = self.get_membership()
        return render(request, self.template_name, {
            "form": AdminSetPasswordForm(), "target_user": membership.user,
        })

    def post(self, request, pk):
        membership = self.get_membership()
        form = AdminSetPasswordForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {
                "form": form, "target_user": membership.user,
            })

        raw_password = (
            form.cleaned_data["password1"]
            if form.cleaned_data["mode"] == AdminSetPasswordForm.MODE_MANUAL
            else None
        )
        password = admin_set_password(
            membership.user, raw_password=raw_password,
            force_change=form.cleaned_data["force_change"],
        )
        log_action(
            AuditAction.PASSWORD_CHANGE, obj=membership.user,
            description=f"Senha redefinida pelo administrador {request.user.email}",
            request=request, is_sensitive=True,
        )
        if raw_password is None:
            messages.success(
                request,
                f"Nova senha provisoria gerada para {membership.user.email}: {password} "
                "(anote agora -- ela nao sera exibida novamente).",
            )
        else:
            messages.success(request, f"Senha de {membership.user.email} definida com sucesso.")
        return redirect("accounts:user-list")


class MembershipPermissionsView(ClinicViewMixin, UpdateView):
    template_name = "accounts/membership_permissions.html"
    form_class = MembershipPermissionForm
    required_permission = "role.manage"
    success_url = reverse_lazy("accounts:user-list")

    def get_object(self, queryset=None):
        return get_object_or_404(
            ClinicMembership.all_objects.select_related("user"),
            pk=self.kwargs["pk"],
            clinic=self.request.clinic,
            is_deleted=False,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["grouped_permissions"] = permissions_by_group()
        context["effective"] = sorted(self.object.effective_permissions())
        return context

    def form_valid(self, form):
        messages.success(self.request, "Permissoes atualizadas.")
        return super().form_valid(form)


class RoleListView(ClinicViewMixin, ListView):
    template_name = "accounts/role_list.html"
    context_object_name = "roles"
    required_permission = "role.manage"

    def get_queryset(self):
        return Role.objects.filter(clinic=self.request.clinic).order_by("name")


class RoleCreateView(ClinicViewMixin, CreateView):
    template_name = "accounts/role_form.html"
    form_class = RoleForm
    required_permission = "role.manage"
    success_url = reverse_lazy("accounts:role-list")

    def form_valid(self, form):
        form.instance.clinic = self.request.clinic
        messages.success(self.request, "Papel criado.")
        return super().form_valid(form)


class RoleUpdateView(ClinicViewMixin, UpdateView):
    template_name = "accounts/role_form.html"
    form_class = RoleForm
    required_permission = "role.manage"
    success_url = reverse_lazy("accounts:role-list")

    def get_queryset(self):
        return Role.objects.filter(clinic=self.request.clinic)

    def form_valid(self, form):
        messages.success(self.request, "Papel atualizado.")
        return super().form_valid(form)


class RoleDeleteView(ClinicViewMixin, DeleteView):
    template_name = "confirm_delete.html"
    required_permission = "role.manage"
    success_url = reverse_lazy("accounts:role-list")

    def get_queryset(self):
        return Role.objects.filter(clinic=self.request.clinic)


def no_permission(request, exception=None):  # pragma: no cover - handler auxiliar
    return render(request, "errors/403.html", status=403)
