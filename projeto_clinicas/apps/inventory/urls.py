from django.urls import path

from apps.inventory import views

app_name = "inventory"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="product-list"),
    path("novo/", views.ProductCreateView.as_view(), name="product-create"),
    path("<uuid:pk>/editar/", views.ProductUpdateView.as_view(), name="product-update"),
    path("<uuid:pk>/entrada/", views.StockEntryView.as_view(), name="stock-entry"),
    path("<uuid:pk>/saida/", views.StockExitView.as_view(), name="stock-exit"),
    path("movimentacoes/", views.StockMovementListView.as_view(), name="movement-list"),
]
