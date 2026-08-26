"""
Mixins de autorizacao para as views.

Toda view do painel deve herdar de :class:`ClinicViewMixin` (ou de
:class:`SuperadminRequiredMixin`, no caso do painel da plataforma). A checagem
e sempre feita no backend -- esconder um botao no template nunca e protecao.
"""
from __future__ import annotations

from typing import Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect

from apps.audit.services import log_denied, log_view
from apps.core.tenancy import get_current_tenant


class ClinicRequiredMixin(LoginRequiredMixin):
    """Exige usuario autenticado com uma clinica ativa."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if getattr(request, "clinic", None) is None:
            if request.user.is_superadmin:
                messages.info(request, "Selecione a clinica que deseja administrar.")
                return redirect("platform:clinic-list")
            if request.user.is_patient:
                return redirect("portal:home")
            messages.error(request, "Seu usuario nao possui vinculo ativo com nenhuma clinica.")
            return redirect("accounts:no-clinic")
        return super().dispatch(request, *args, **kwargs)


class ClinicPermissionMixin(ClinicRequiredMixin):
    """
    Exige uma permissao especifica na clinica ativa.

    Defina ``required_permission`` (str) ou sobrescreva
    :meth:`get_required_permission`.
    """

    required_permission: Optional[str] = None

    def get_required_permission(self) -> Optional[str]:
        return self.required_permission

    def dispatch(self, request, *args, **kwargs):
        response = self._check_permission(request)
        if response is not None:
            return response
        return super().dispatch(request, *args, **kwargs)

    def _check_permission(self, request):
        if not request.user.is_authenticated or getattr(request, "clinic", None) is None:
            return None
        codename = self.get_required_permission()
        if codename and not request.user.has_clinic_perm(codename, request.clinic):
            log_denied(
                f"Permissao '{codename}' negada em {request.path}",
                request=request,
            )
            raise PermissionDenied(
                "Voce nao possui permissao para executar esta acao nesta clinica."
            )
        return None


class ClinicViewMixin(ClinicPermissionMixin):
    """
    Base das views do painel da clinica.

    * garante contexto de tenant;
    * confere a permissao declarada;
    * restringe o queryset ao tenant ativo (defesa em profundidade).
    """

    #: Modelo do qual a view lista/edita registros.
    model = None
    #: Quando True, registra em auditoria o acesso ao objeto (dado sensivel).
    audit_object_access = False
    audit_description = ""

    def get_queryset(self):
        queryset = super().get_queryset()
        clinic = getattr(self.request, "clinic", None) or get_current_tenant()
        if clinic is None:
            return queryset.none()
        if hasattr(queryset.model, "clinic_id"):
            queryset = queryset.filter(clinic_id=clinic.pk)
        return queryset

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        clinic = getattr(self.request, "clinic", None)
        obj_clinic_id = getattr(obj, "clinic_id", None)
        if obj_clinic_id is not None and clinic is not None and str(obj_clinic_id) != str(clinic.pk):
            # Nao revelamos a existencia do registro de outra clinica.
            log_denied(
                f"Tentativa de acesso a objeto de outra clinica ({obj._meta.label})",
                request=self.request,
                obj=obj,
            )
            raise Http404
        if self.audit_object_access:
            log_view(obj, request=self.request, description=self.audit_description)
        return obj


class SuperadminRequiredMixin(LoginRequiredMixin):
    """Exige perfil SUPERADMIN (painel /platform/)."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_superadmin:
            log_denied("Tentativa de acesso ao painel da plataforma", request=request)
            raise PermissionDenied("Area restrita a administradores da plataforma.")
        return super().dispatch(request, *args, **kwargs)


class PatientRequiredMixin(LoginRequiredMixin):
    """Exige que o usuario seja um paciente com cadastro vinculado."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_patient:
            raise PermissionDenied("Area exclusiva do portal do paciente.")
        return super().dispatch(request, *args, **kwargs)


class AuditCreateUpdateMixin:
    """Mensagens padronizadas de sucesso em formularios."""

    success_message = "Registro salvo com sucesso."

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Verifique os campos destacados no formulario.")
        return super().form_invalid(form)
