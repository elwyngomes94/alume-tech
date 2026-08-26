from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("", views.DocumentListView.as_view(), name="list"),
    path("enviar/", views.DocumentUploadView.as_view(), name="upload"),
    path("<uuid:pk>/download/", views.DocumentDownloadView.as_view(), name="download"),
    path("<uuid:pk>/excluir/", views.DocumentDeleteView.as_view(), name="delete"),
    path("categorias/", views.DocumentCategoryListView.as_view(), name="category-list"),
    path("categorias/nova/", views.DocumentCategoryCreateView.as_view(), name="category-create"),
]
