"""Formularios de autenticacao, perfil e gestao de usuarios da clinica."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    SetPasswordForm,
)
from django.core.exceptions import ValidationError

from apps.accounts.models import ApiToken, Role, User
from apps.accounts.permissions import (
    PERMISSION_CATALOG,
    Roles,
    permissions_by_group,
)
from apps.tenants.models import ClinicMembership

BOOTSTRAP_INPUT = {"class": "form-control"}
BOOTSTRAP_SELECT = {"class": "form-select"}
BOOTSTRAP_CHECK = {"class": "form-check-input"}


class BootstrapFormMixin:
    """Aplica classes do Bootstrap 5 automaticamente."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault("class", "form-control")
            else:
                widget.attrs.setdefault("class", "form-control")
            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"
            if isinstance(widget, forms.TimeInput):
                widget.input_type = "time"


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    username = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "E-mail ou senha invalidos.",
        "inactive": "Este usuario esta inativo.",
    }


class MFAVerifyForm(BootstrapFormMixin, forms.Form):
    code = forms.CharField(
        label="Codigo de verificacao",
        max_length=6,
        widget=forms.TextInput(
            attrs={"autofocus": True, "inputmode": "numeric", "autocomplete": "one-time-code"}
        ),
    )


class MFASetupForm(MFAVerifyForm):
    """Confirma a ativacao do MFA validando o primeiro codigo."""


class JJAPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass


class JJASetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "email", "phone", "birth_date", "avatar"]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}


class ClinicUserForm(BootstrapFormMixin, forms.ModelForm):
    """
    Cadastro/edicao de usuario da clinica pelo administrador local.

    O administrador NAO pode criar superadministradores nem alterar usuarios de
    outra clinica -- a view garante o escopo e o formulario limita os perfis.
    """

    role = forms.ChoiceField(
        label="Perfil",
        choices=[(value, label) for value, label in Roles.CHOICES if value != Roles.SUPERADMIN],
    )
    custom_role = forms.ModelChoiceField(
        label="Papel personalizado",
        queryset=Role.objects.none(),
        required=False,
        help_text="Opcional. Sobrescreve as permissoes padrao do perfil.",
    )
    job_title = forms.CharField(label="Cargo", max_length=80, required=False)
    send_invite = forms.BooleanField(
        label="Enviar senha provisoria por e-mail", required=False, initial=True
    )

    class Meta:
        model = User
        fields = ["full_name", "email", "cpf", "phone", "is_active"]

    def __init__(self, *args, clinic=None, membership=None, **kwargs):
        self.clinic = clinic
        self.membership = membership
        super().__init__(*args, **kwargs)
        if clinic is not None:
            self.fields["custom_role"].queryset = Role.objects.filter(
                clinic=clinic, is_active=True
            )
        if membership is not None:
            self.fields["role"].initial = membership.role
            self.fields["custom_role"].initial = membership.custom_role
            self.fields["job_title"].initial = membership.job_title
        # OBS: nao usar "self.instance.pk" aqui -- o User tem UUIDField com
        # default=uuid.uuid4, entao mesmo uma instancia nova (ainda nao salva)
        # ja possui um pk gerado. "is_saved" reflete corretamente se a
        # instancia ja existe no banco.
        if self.instance.is_saved:
            self.fields["email"].disabled = True
            self.fields["send_invite"].initial = False

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if self.instance.is_saved:
            return self.instance.email
        existing = User.objects.filter(email__iexact=email).first()
        if existing and self.clinic and existing.membership_for(self.clinic):
            raise ValidationError("Este usuario ja possui vinculo com esta clinica.")
        return email

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role == Roles.SUPERADMIN:
            raise ValidationError("Perfil nao permitido.")
        return role


class RoleForm(BootstrapFormMixin, forms.ModelForm):
    """Editor de papel personalizado com selecao granular de permissoes."""

    permissions = forms.MultipleChoiceField(
        label="Permissoes",
        required=False,
        choices=[(code, label) for code, label, _group in PERMISSION_CATALOG],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Role
        fields = ["name", "base_role", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["base_role"].choices = [
            (value, label) for value, label in Roles.CHOICES if value != Roles.SUPERADMIN
        ]
        if self.instance.is_saved:
            self.fields["permissions"].initial = self.instance.permissions or []

    @property
    def grouped_permissions(self):
        return permissions_by_group()

    def save(self, commit=True):
        role = super().save(commit=False)
        role.permissions = list(self.cleaned_data.get("permissions") or [])
        if commit:
            role.save()
        return role


class MembershipPermissionForm(BootstrapFormMixin, forms.ModelForm):
    """Ajuste fino de permissoes de um usuario especifico na clinica."""

    extra_permissions = forms.MultipleChoiceField(
        label="Permissoes adicionais",
        required=False,
        choices=[(code, label) for code, label, _g in PERMISSION_CATALOG],
        widget=forms.CheckboxSelectMultiple,
    )
    denied_permissions = forms.MultipleChoiceField(
        label="Permissoes negadas",
        required=False,
        choices=[(code, label) for code, label, _g in PERMISSION_CATALOG],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ClinicMembership
        fields = ["role", "custom_role", "job_title", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [
            (value, label) for value, label in Roles.CHOICES if value != Roles.SUPERADMIN
        ]
        if self.instance.is_saved:
            self.fields["custom_role"].queryset = Role.objects.filter(
                clinic=self.instance.clinic, is_active=True
            )
            self.fields["extra_permissions"].initial = self.instance.extra_permissions or []
            self.fields["denied_permissions"].initial = self.instance.denied_permissions or []

    def save(self, commit=True):
        membership = super().save(commit=False)
        membership.extra_permissions = list(self.cleaned_data.get("extra_permissions") or [])
        membership.denied_permissions = list(self.cleaned_data.get("denied_permissions") or [])
        if commit:
            membership.save()
        return membership


class ApiTokenForm(BootstrapFormMixin, forms.ModelForm):
    expires_in_days = forms.IntegerField(
        label="Validade (dias)", min_value=1, max_value=730, initial=365
    )

    class Meta:
        model = ApiToken
        fields = ["name"]


class AdminSetPasswordForm(BootstrapFormMixin, forms.Form):
    """
    Definir/redefinir a senha de um usuario por um administrador.

    Duas opcoes: gerar uma senha provisoria aleatoria (recomendado -- nunca
    fica salva em nenhum lugar alem da tela de confirmacao) ou digitar uma
    senha especifica (validada pelas mesmas regras de forca do cadastro
    normal).
    """

    MODE_GENERATE = "generate"
    MODE_MANUAL = "manual"
    MODE_CHOICES = [
        (MODE_GENERATE, "Gerar senha provisoria automaticamente (recomendado)"),
        (MODE_MANUAL, "Definir uma senha especifica"),
    ]

    mode = forms.ChoiceField(
        label="Como definir a senha", choices=MODE_CHOICES, widget=forms.RadioSelect,
        initial=MODE_GENERATE,
    )
    password1 = forms.CharField(
        label="Nova senha", required=False, widget=forms.PasswordInput(render_value=False),
    )
    password2 = forms.CharField(
        label="Confirmar nova senha", required=False,
        widget=forms.PasswordInput(render_value=False),
    )
    force_change = forms.BooleanField(
        label="Exigir que o usuario troque a senha no proximo login",
        required=False, initial=True,
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("mode") == self.MODE_MANUAL:
            password1 = cleaned.get("password1")
            password2 = cleaned.get("password2")
            if not password1 or not password2:
                raise ValidationError("Informe e confirme a nova senha.")
            if password1 != password2:
                raise ValidationError("As senhas informadas nao coincidem.")
            from django.contrib.auth.password_validation import validate_password

            validate_password(password1)
        return cleaned
