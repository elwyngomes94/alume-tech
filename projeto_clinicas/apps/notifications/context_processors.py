"""Disponibiliza o contador de notificacoes nao lidas no layout."""
from __future__ import annotations


def notifications_context(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"unread_notifications": 0, "recent_notifications": []}

    from apps.notifications.models import Notification

    queryset = Notification.objects.filter(recipient=user).order_by("-created_at")
    return {
        "unread_notifications": queryset.filter(read_at__isnull=True).count(),
        "recent_notifications": list(queryset[:6]),
    }
