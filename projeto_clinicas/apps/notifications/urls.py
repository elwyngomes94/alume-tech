from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("<uuid:pk>/ler/", views.NotificationReadView.as_view(), name="read"),
    path("ler-todas/", views.NotificationReadAllView.as_view(), name="read-all"),
    path("nao-lidas/", views.NotificationUnreadCountView.as_view(), name="unread-count"),
]
