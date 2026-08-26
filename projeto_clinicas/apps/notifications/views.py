"""Views de notificacoes internas."""
from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from apps.notifications.models import Notification


class NotificationListView(LoginRequiredMixin, ListView):
    """Notificacoes sempre filtradas pelo proprio destinatario."""

    model = Notification
    template_name = "notifications/notification_list.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        queryset = Notification.objects.filter(recipient=self.request.user)
        if self.request.GET.get("unread") == "1":
            queryset = queryset.filter(read_at__isnull=True)
        return queryset.select_related("clinic").order_by("-created_at")


class NotificationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(Notification.objects.all(), pk=pk, recipient=request.user)
        notification.mark_as_read()
        if notification.url:
            return redirect(notification.url)
        return redirect("notifications:list")


class NotificationReadAllView(LoginRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return redirect("notifications:list")


class NotificationUnreadCountView(LoginRequiredMixin, View):
    """Contador consumido pelo topo da interface (HTMX/fetch)."""

    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user, read_at__isnull=True
        ).count()
        return JsonResponse({"unread": count})
