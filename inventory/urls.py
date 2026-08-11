from django.urls import path

from .views import (
    DashboardSummaryView,
    MaterialDetailView,
    MaterialListCreateView,
    MaterialCatalogView,
    EngineerConnectionCheckView,
    ReportView,
    StockTransactionListCreateView,
    MaterialRequestListView,
    MaterialRequestSummaryView,
    MaterialRequestReviewView,
    MaterialRequestCreateView,
    AIInsightsView,
    EngineerConnectionView,
    # Phase 3
    ProductListCreateView,
    ProductDetailView,
    ProductBomView,
    MaterialQuickCreateView,
    # Phase 4
    ImpliedDemandInsightView,
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
    path("engineer-catalog/", MaterialCatalogView.as_view(), name="engineer-catalog"),
    path("connections/check/", EngineerConnectionCheckView.as_view(), name="connections-check"),
    path("engineers/status/", EngineerConnectionCheckView.as_view(), name="engineers-status"),

    # Material Requests
    path("requests/list/", MaterialRequestListView.as_view(), name="request-list"),
    path("material-requests/summary/", MaterialRequestSummaryView.as_view(), name="request-summary"),
    path("requests/<int:pk>/review/", MaterialRequestReviewView.as_view(), name="request-review"),
    path("requests/create/", MaterialRequestCreateView.as_view(), name="request-create"),

    # Connected Engineers (Team Access Control)
    path("connections/", EngineerConnectionView.as_view(), name="connections-list"),
    path("connections/<int:pk>/", EngineerConnectionView.as_view(), name="connections-detail"),

    # Phase 3 — Products & BOM
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path("products/<int:pk>/bom/", ProductBomView.as_view(), name="product-bom"),
    # Quick-create a material from the BOM mini-form (isolated serializer — does NOT change
    # MaterialCreateSerializer behaviour on the main Add Material page)
    path("materials/quick-create/", MaterialQuickCreateView.as_view(), name="material-quick-create"),

    # Phase 4 — Implied Demand Insights
    path("products/insights/implied-demand/", ImpliedDemandInsightView.as_view(), name="product-implied-demand-insights"),
    path("products/implied-demand/", ImpliedDemandInsightView.as_view(), name="product-implied-demand"),
]
