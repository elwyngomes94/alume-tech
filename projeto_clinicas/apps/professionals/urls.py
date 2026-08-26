from django.urls import path

from apps.professionals import views

app_name = "professionals"

urlpatterns = [
    path("", views.ProfessionalListView.as_view(), name="list"),
    path("novo/", views.ProfessionalCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.ProfessionalDetailView.as_view(), name="detail"),
    path("<uuid:pk>/editar/", views.ProfessionalUpdateView.as_view(), name="update"),
    path("<uuid:pk>/desativar/", views.ProfessionalDeleteView.as_view(), name="delete"),
]
