from django.urls import path

from .views import (
    DashboardSummaryView,
    MaterialDetailView,
    MaterialListCreateView,
    MaterialCatalogView,
    ReportView,
    StockTransactionListCreateView,
    MaterialRequestListView,
    MaterialRequestReviewView,
    MaterialRequestCreateView,
    AIInsightsView,
)


app_name = "inventory"

urlpatterns = [
    path("materials/", MaterialListCreateView.as_view(), name="material-list-create"),
    path("materials/<int:pk>/", MaterialDetailView.as_view(), name="material-detail"),
    path(
        "transactions/",
        StockTransactionListCreateView.as_view(),
        name="transaction-list-create",
    ),
    path("dashboard/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("reports/", ReportView.as_view(), name="reports"),
    path("insights/", AIInsightsView.as_view(), name="insights"),
    
    # Site B — Public API Key-protected endpoints
    path("materials/catalog/", MaterialCatalogView.as_view(), name="material-catalog"),

    # Material Requests
    path("requests/list/", MaterialRequestListView.as_view(), name="request-list"),
    path("requests/<int:pk>/review/", MaterialRequestReviewView.as_view(), name="request-review"),
    path("requests/create/", MaterialRequestCreateView.as_view(), name="request-create"),
]
