from django.urls import path

from apps.finance import views

app_name = "finance"

urlpatterns = [
    path("", views.FinanceDashboardView.as_view(), name="dashboard"),
    # Pagamentos pendentes (recepcao -- "dar baixa")
    path("pendentes/", views.PendingPaymentsView.as_view(), name="pending-payments"),
    path(
        "receber/<uuid:pk>/dar-baixa/",
        views.AppointmentReceivablePayView.as_view(),
        name="appointment-receivable-pay",
    ),
    # Contas a receber
    path("receber/", views.ReceivableListView.as_view(), name="receivable-list"),
    path("receber/novo/", views.ReceivableCreateView.as_view(), name="receivable-create"),
    path("receber/<uuid:pk>/", views.ReceivableDetailView.as_view(), name="receivable-detail"),
    path(
        "receber/<uuid:pk>/editar/",
        views.ReceivableUpdateView.as_view(),
        name="receivable-update",
    ),
    path("receber/<uuid:pk>/pagar/", views.ReceivablePayView.as_view(), name="receivable-pay"),
    path(
        "receber/<uuid:pk>/cancelar/",
        views.ReceivableCancelView.as_view(),
        name="receivable-cancel",
    ),
    # Contas a pagar
    path("pagar/", views.PayableListView.as_view(), name="payable-list"),
    path("pagar/novo/", views.PayableCreateView.as_view(), name="payable-create"),
    path("pagar/<uuid:pk>/", views.PayableDetailView.as_view(), name="payable-detail"),
    path("pagar/<uuid:pk>/editar/", views.PayableUpdateView.as_view(), name="payable-update"),
    path("pagar/<uuid:pk>/pagar/", views.PayablePayView.as_view(), name="payable-pay"),
    path("pagar/<uuid:pk>/cancelar/", views.PayableCancelView.as_view(), name="payable-cancel"),
    # Fluxo de caixa e lancamento avulso
    path("fluxo-caixa/", views.CashFlowView.as_view(), name="cashflow"),
    path("lancamento/novo/", views.ManualTransactionCreateView.as_view(), name="transaction-create"),
    # Configuracoes
    path("configuracoes/", views.FinanceSettingsView.as_view(), name="settings"),
    path(
        "configuracoes/categoria/nova/",
        views.FinancialCategoryCreateView.as_view(),
        name="category-create",
    ),
    path(
        "configuracoes/categoria/<uuid:pk>/editar/",
        views.FinancialCategoryUpdateView.as_view(),
        name="category-update",
    ),
    path(
        "configuracoes/centro-custo/novo/",
        views.CostCenterCreateView.as_view(),
        name="costcenter-create",
    ),
    path(
        "configuracoes/centro-custo/<uuid:pk>/editar/",
        views.CostCenterUpdateView.as_view(),
        name="costcenter-update",
    ),
    path(
        "configuracoes/forma-pagamento/nova/",
        views.PaymentMethodCreateView.as_view(),
        name="paymentmethod-create",
    ),
    path(
        "configuracoes/forma-pagamento/<uuid:pk>/editar/",
        views.PaymentMethodUpdateView.as_view(),
        name="paymentmethod-update",
    ),
    # Comissoes
    path("comissoes/", views.CommissionRuleListView.as_view(), name="commission-list"),
    path("comissoes/nova/", views.CommissionRuleCreateView.as_view(), name="commission-create"),
    path(
        "comissoes/<uuid:pk>/editar/",
        views.CommissionRuleUpdateView.as_view(),
        name="commission-update",
    ),
]
