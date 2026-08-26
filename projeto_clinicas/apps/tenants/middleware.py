"""
Middleware de tenant.

Resolve a clinica ativa da requisicao **a partir do vinculo do usuario**, nunca
apenas a partir da URL. A URL pode indicar a clinica desejada, mas o vinculo e
sempre reconferido no banco antes de ativar o tenant.
"""
from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.deprecation import MiddlewareMixin

from apps.core.tenancy import clear_current_tenant, set_current_tenant

logger = logging.getLogger("jja.security")

SESSION_CLINIC_KEY = "jja_active_clinic_id"

#: Prefixos que nao exigem tenant ativo.
TENANT_EXEMPT_PREFIXES = (
    "/accounts/",
    "/platform/",
    "/django-admin/",
    "/static/",
    "/media/",
    "/healthz",
)


class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.clinic = None
        request.membership = None
        request.clinic_permissions = frozenset()

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            clear_current_tenant()
            return None

        clinic = self._resolve_clinic(request, user)
        if clinic is None:
            clear_current_tenant()
            return None

        set_current_tenant(clinic)
        request.clinic = clinic
        membership = None if user.is_superadmin else user.membership_for(clinic)
        request.membership = membership
        request.clinic_permissions = frozenset(user.clinic_permissions(clinic))
        return None

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Se a URL indicar uma clinica, revalida o vinculo antes de trocar."""
        slug = view_kwargs.get("clinic_slug")
        user = getattr(request, "user", None)
        if not slug or user is None or not user.is_authenticated:
            return None

        from apps.clinics.models import Clinic

        clinic = Clinic.objects.filter(slug=slug).first()
        if clinic is None or not user.can_access_clinic(clinic):
            logger.warning(
                "tentativa-de-acesso-por-url-sem-vinculo user=%s slug=%s", user.email, slug
            )
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Voce nao possui acesso a esta clinica.")

        set_current_tenant(clinic)
        request.clinic = clinic
        request.membership = None if user.is_superadmin else user.membership_for(clinic)
        request.clinic_permissions = frozenset(user.clinic_permissions(clinic))
        return None

    def process_response(self, request, response):
        clear_current_tenant()
        return response

    # ------------------------------------------------------------------
    def _resolve_clinic(self, request, user):
        from apps.clinics.models import Clinic

        requested_id = request.session.get(SESSION_CLINIC_KEY)

        clinic = None
        if requested_id:
            try:
                clinic = Clinic.objects.filter(pk=requested_id).first()
            except (ValueError, TypeError, DjangoValidationError):
                request.session.pop(SESSION_CLINIC_KEY, None)
                clinic = None

        if clinic is not None:
            # Reconferencia obrigatoria: o id veio da sessao/URL (dado do cliente).
            if not user.can_access_clinic(clinic):
                logger.warning(
                    "tentativa-de-acesso-a-clinica-sem-vinculo user=%s clinic=%s path=%s",
                    user.email,
                    clinic.pk,
                    request.path,
                )
                request.session.pop(SESSION_CLINIC_KEY, None)
                clinic = None
            elif not clinic.is_operational and not user.is_superadmin:
                clinic = None

        if clinic is None and not user.is_superadmin:
            membership = (
                user.memberships_queryset()
                .filter(clinic__status=Clinic.Status.ACTIVE)
                .order_by("-is_default", "created_at")
                .first()
            )
            clinic = membership.clinic if membership else None
            if clinic is not None:
                request.session[SESSION_CLINIC_KEY] = str(clinic.pk)

        return clinic
