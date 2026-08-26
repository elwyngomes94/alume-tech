from django.urls import path

from apps.scheduling import views

app_name = "scheduling"

urlpatterns = [
    path("", views.AgendaDayView.as_view(), name="agenda-day"),
    path("semana/", views.AgendaWeekView.as_view(), name="agenda-week"),
    path("mes/", views.AgendaMonthView.as_view(), name="agenda-month"),
    path("lista/", views.AgendaListView.as_view(), name="agenda-list"),
    path("horarios/", views.SlotsApiView.as_view(), name="slots"),
    # Agendamentos
    path("agendamento/novo/", views.AppointmentCreateView.as_view(), name="appointment-create"),
    path("agendamento/<uuid:pk>/", views.AppointmentDetailView.as_view(), name="appointment-detail"),
    path(
        "agendamento/<uuid:pk>/editar/",
        views.AppointmentUpdateView.as_view(),
        name="appointment-update",
    ),
    path(
        "agendamento/<uuid:pk>/status/<str:status>/",
        views.AppointmentStatusView.as_view(),
        name="appointment-status",
    ),
    path(
        "agendamento/<uuid:pk>/remarcar/",
        views.AppointmentRescheduleView.as_view(),
        name="appointment-reschedule",
    ),
    # Disponibilidade
    path("disponibilidade/", views.ScheduleTemplateListView.as_view(), name="schedule-list"),
    path(
        "disponibilidade/nova/",
        views.ScheduleTemplateCreateView.as_view(),
        name="schedule-create",
    ),
    path(
        "disponibilidade/<uuid:pk>/editar/",
        views.ScheduleTemplateUpdateView.as_view(),
        name="schedule-update",
    ),
    path(
        "disponibilidade/<uuid:pk>/excluir/",
        views.ScheduleTemplateDeleteView.as_view(),
        name="schedule-delete",
    ),
    path("bloqueio/novo/", views.ScheduleBlockCreateView.as_view(), name="block-create"),
    path("bloqueio/<uuid:pk>/excluir/", views.ScheduleBlockDeleteView.as_view(), name="block-delete"),
    # Lista de espera
    path("espera/", views.WaitingListView.as_view(), name="waiting-list"),
    path("espera/nova/", views.WaitingListCreateView.as_view(), name="waiting-create"),
    path(
        "espera/<uuid:pk>/status/<str:status>/",
        views.WaitingListUpdateStatusView.as_view(),
        name="waiting-status",
    ),
]
