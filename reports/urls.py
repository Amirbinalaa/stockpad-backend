from django.urls import path

from .views import ProcurementPlanningReportView

app_name = "reports"

urlpatterns = [
    path(
        "procurement-planning/",
        ProcurementPlanningReportView.as_view(),
        name="procurement-planning",
    ),
]
