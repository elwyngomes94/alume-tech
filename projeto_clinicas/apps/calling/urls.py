"""
URLs de chamada de pacientes.

Duas superficies distintas no mesmo namespace ``calling``:

* ``/app/chamadas/...`` -- painel de staff (login obrigatorio, exige o
  modulo ``patient_calling`` e permissoes ``calling.*``);
* ``/chamada/<token>/...`` -- pagina publica do paciente (sem login, so o
  token opaco da senha). Fica fora de ``/app/`` de proposito: a URL de
  staff nunca deve ser confundida com a URL que o paciente recebe no QR.
"""
from django.urls import path

from apps.calling import public_views, views

app_name = "calling"

urlpatterns = [
    # --- Painel de staff --------------------------------------------------
    path("app/chamadas/painel/", views.PanelTVView.as_view(), name="panel-tv"),
    path("app/chamadas/painel/status/", views.PanelStatusApiView.as_view(), name="panel-status"),
    path("app/chamadas/fila/", views.QueueRecallableView.as_view(), name="queue-status"),
    path("app/chamadas/configuracoes/", views.CallPanelConfigView.as_view(), name="config"),
    path("app/chamadas/<uuid:pk>/rechamar/", views.TicketRecallView.as_view(), name="recall"),
    path("app/chamadas/<uuid:pk>/qr/", views.TicketQRView.as_view(), name="ticket-qr"),
    # --- Pagina publica do paciente -----------------------------------------
    path("chamada/sw-push.js", public_views.ServiceWorkerView.as_view(), name="service-worker"),
    path("chamada/<str:token>/", public_views.PatientTicketView.as_view(), name="patient-ticket"),
    path(
        "chamada/<str:token>/status/",
        public_views.PatientTicketStatusView.as_view(),
        name="patient-ticket-status",
    ),
    path(
        "chamada/<str:token>/push/",
        public_views.PatientPushSubscribeView.as_view(),
        name="patient-push-subscribe",
    ),
]
