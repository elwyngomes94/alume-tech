"""Views de documentos: listagem, upload e download autenticado."""
from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView

from apps.audit.models import AuditAction
from apps.audit.services import log_action
from apps.core.middleware import client_ip
from apps.core.mixins import ClinicViewMixin
from apps.documents import services
from apps.documents.forms import DocumentCategoryForm, DocumentForm
from apps.documents.models import Document, DocumentCategory


class DocumentListView(ClinicViewMixin, ListView):
    model = Document
    template_name = "documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 30
    required_permission = "document.view"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("patient", "category", "uploaded_by")
        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(patient__full_name__icontains=search)
            )
        category = self.request.GET.get("category", "")
        if category:
            queryset = queryset.filter(category_id=category)
        patient = self.request.GET.get("patient", "")
        if patient:
            queryset = queryset.filter(patient_id=patient)
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = DocumentCategory.objects.filter(is_active=True)
        return context


class DocumentUploadView(ClinicViewMixin, CreateView):
    model = Document
    form_class = DocumentForm
    template_name = "documents/document_form.html"
    required_permission = "document.add"
    success_url = reverse_lazy("documents:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        patient_id = self.request.GET.get("patient")
        if patient_id:
            from apps.patients.models import Patient

            kwargs["patient"] = Patient.objects.filter(pk=patient_id).first()
        return kwargs

    def form_valid(self, form):
        document = form.save(commit=False)
        document.clinic = self.request.clinic
        document.uploaded_by = self.request.user
        document.save()
        self.object = document
        log_action(
            AuditAction.UPLOAD,
            obj=document,
            description=f"Upload do documento '{document.title}'",
            request=self.request,
            is_sensitive=document.is_sensitive,
        )
        messages.success(self.request, "Documento enviado com seguranca.")
        if document.patient_id:
            return redirect("patients:detail", pk=document.patient_id)
        return redirect(self.success_url)


class DocumentDownloadView(ClinicViewMixin, View):
    """
    Unico caminho de saida de um arquivo privado.

    Confere tenant, permissao e vinculo assistencial; registra auditoria e
    entrega o arquivo com cabecalhos que impedem cache.
    """

    required_permission = "document.download"

    def get(self, request, pk):
        document = get_object_or_404(Document.objects.select_related("patient", "category"),
                                     pk=pk)
        services.assert_can_access_document(request.user, request.clinic, document)

        try:
            handle = document.file.open("rb")
        except FileNotFoundError as exc:  # pragma: no cover - arquivo removido do disco
            raise Http404("Arquivo nao encontrado.") from exc

        services.register_access(document, request.user, client_ip(request), "download")
        log_action(
            AuditAction.DOWNLOAD,
            obj=document,
            description=f"Download do documento '{document.title}'",
            request=request,
            is_sensitive=document.is_sensitive,
        )

        content_type = (
            document.content_type
            or mimetypes.guess_type(document.original_name or "")[0]
            or "application/octet-stream"
        )
        filename = document.original_name or f"documento.{document.extension or 'bin'}"
        response = FileResponse(handle, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class DocumentDeleteView(ClinicViewMixin, View):
    required_permission = "document.delete"

    def post(self, request, pk):
        document = get_object_or_404(Document.objects.all(), pk=pk)
        patient_id = document.patient_id
        document.delete(user=request.user)
        messages.success(request, "Documento excluido (exclusao logica com auditoria).")
        if patient_id:
            return redirect("patients:detail", pk=patient_id)
        return redirect("documents:list")


class DocumentCategoryListView(ClinicViewMixin, ListView):
    model = DocumentCategory
    template_name = "documents/category_list.html"
    context_object_name = "categories"
    required_permission = "document.view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = DocumentCategoryForm()
        return context


class DocumentCategoryCreateView(ClinicViewMixin, CreateView):
    model = DocumentCategory
    form_class = DocumentCategoryForm
    template_name = "documents/category_list.html"
    required_permission = "document.add"
    success_url = reverse_lazy("documents:category-list")

    def form_valid(self, form):
        messages.success(self.request, "Categoria criada.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Nao foi possivel criar a categoria.")
        return redirect(self.success_url)
