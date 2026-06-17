from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import models
import hashlib
import hmac
import json
import requests

from settings_app.models import UserPreference

from .models import Material, StockTransaction, MaterialRequest
from .serializers import (
    MaterialCreateSerializer,
    MaterialSerializer,
    StockTransactionSerializer,
    MaterialRequestSerializer,
    MaterialRequestReviewSerializer,
    MaterialRequestCreateSerializer,
)
from django.conf import settings


class MaterialListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Material.objects.filter(
            user=self.request.user, is_active=True
        ).order_by("name")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MaterialCreateSerializer
        return MaterialSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MaterialDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MaterialSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Material.objects.filter(user=self.request.user)


class StockTransactionListCreateView(generics.ListCreateAPIView):
    serializer_class = StockTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return StockTransaction.objects.filter(
            material__user=self.request.user
        ).select_related("material").order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(performed_by=self.request.user)


class DashboardSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        materials = Material.objects.filter(
            user=request.user, is_active=True
        ).order_by("name")
        data = []
        for m in materials:
            threshold_percent = m.low_stock_threshold_percent
            is_low_stock = False
            if threshold_percent is not None and threshold_percent > 0:
                threshold_value = 100 * (threshold_percent / 100)
                is_low_stock = float(m.current_quantity) < float(threshold_value)

            data.append({
                "id": m.id,
                "name": m.name,
                "unit": m.unit,
                "current_quantity": m.current_quantity,
                "low_stock_threshold_percent": m.low_stock_threshold_percent,
                "is_low_stock": is_low_stock,
            })
        return Response(data)


class ReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        material_id = request.query_params.get("material")
        type_ = request.query_params.get("type", "both")
        period = request.query_params.get("period", "all")
        specific_date = request.query_params.get("date")

        qs = StockTransaction.objects.filter(
            material__user=request.user
        ).select_related("material", "performed_by")

        if material_id and material_id != "all":
            qs = qs.filter(material_id=material_id)

        if type_ in [StockTransaction.TYPE_IN, StockTransaction.TYPE_OUT]:
            qs = qs.filter(type=type_)

        now = timezone.now()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            qs = qs.filter(created_at__gte=start)
        elif period == "week":
            start = now - timezone.timedelta(days=7)
            qs = qs.filter(created_at__gte=start)
        elif period == "month":
            start = now - timezone.timedelta(days=30)
            qs = qs.filter(created_at__gte=start)
        elif period == "specific" and specific_date:
            qs = qs.filter(created_at__date=specific_date)

        serializer = StockTransactionSerializer(qs, many=True)
        totals = qs.aggregate(
            total_in=Sum("quantity", filter=models.Q(type=StockTransaction.TYPE_IN)),
            total_out=Sum("quantity", filter=models.Q(type=StockTransaction.TYPE_OUT)),
        )
        summary = {
            "total_in": totals["total_in"] or 0,
            "total_out": totals["total_out"] or 0,
            "net": (totals["total_in"] or 0) - (totals["total_out"] or 0),
            "count": qs.count(),
        }
        return Response({"summary": summary, "results": serializer.data})


# ── Material Requests ──────────────────────────────────

class HasSiteBAPIKey(permissions.BasePermission):
    """
    Custom permission to allow requests from Site B using an API Key.
    """
    def has_permission(self, request, view):
        api_key = request.headers.get("X-Site-B-API-Key")
        expected_key = getattr(settings, "SITE_B_API_KEY", None)
        return api_key == expected_key


def _build_webhook_headers(payload: dict) -> dict:
    """
    Serialize payload to JSON bytes and compute an HMAC-SHA256 signature
    using SITE_A_API_KEY. Returns headers dict ready to pass to requests.post().
    """
    secret = getattr(settings, "SITE_A_API_KEY", "").encode("utf-8")
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Site-A-Signature": signature,
    }


class MaterialCatalogView(generics.ListAPIView):
    """
    Read-only materials catalog for Site B.
    Returns id, name, unit, and current_quantity for all active materials.
    Protected by the same X-Site-B-API-Key used for request creation.
    """
    permission_classes = [HasSiteBAPIKey]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        materials = Material.objects.filter(is_active=True).order_by("name").values(
            "id", "name", "unit", "current_quantity"
        )
        return Response(list(materials))


class MaterialRequestListView(generics.ListAPIView):
    serializer_class = MaterialRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = MaterialRequest.objects.filter(
            material__user=self.request.user
        ).select_related("material", "reviewed_by")
        status = self.request.query_params.get("status")
        if status:
            queryset = queryset.filter(status=status)
        return queryset


class MaterialRequestReviewView(generics.UpdateAPIView):
    serializer_class = MaterialRequestReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["patch"]

    def get_queryset(self):
        return MaterialRequest.objects.filter(
            material__user=self.request.user
        ).select_related("material")

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        if instance.status != MaterialRequest.STATUS_PENDING:
            return Response(
                {"detail": "This request has already been reviewed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data["status"]
        review_notes = serializer.validated_data.get("review_notes", instance.review_notes)

        # Run database changes inside an atomic transaction block
        with db_transaction.atomic():
            # Refetch with select_for_update to avoid race conditions
            instance = MaterialRequest.objects.select_for_update().get(pk=instance.pk)

            # Re-verify the status under the lock
            if instance.status != MaterialRequest.STATUS_PENDING:
                return Response(
                    {"detail": "This request has already been reviewed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if new_status == MaterialRequest.STATUS_APPROVED:
                material = Material.objects.select_for_update().get(pk=instance.material_id)
                qty = instance.quantity

                if material.current_quantity < qty:
                    return Response(
                        {"detail": "Insufficient stock to approve this request."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                material.current_quantity -= qty
                material.save(update_fields=["current_quantity"])

                requester_email = instance.requester_email or request.data.get("requester_email", "")
                StockTransaction.objects.create(
                    material=material,
                    type=StockTransaction.TYPE_OUT,
                    quantity=qty,
                    notes=f"Approved request from {requester_email}"[:255],
                    performed_by=request.user,
                )

            instance.status = new_status
            instance.review_notes = review_notes
            instance.reviewed_by = request.user
            instance.updated_at = timezone.now()
            instance.save(update_fields=["status", "review_notes", "reviewed_by", "updated_at"])

        # Trigger webhook AFTER transaction block commits to prevent blocking db transaction locks
        if instance.webhook_url and new_status in [MaterialRequest.STATUS_APPROVED, MaterialRequest.STATUS_DENIED]:
            payload = {
                "id": instance.id,
                "status": instance.status,
            }
            try:
                requests.post(
                    instance.webhook_url,
                    data=json.dumps(payload, separators=(",", ":")),
                    headers=_build_webhook_headers(payload),
                    timeout=5,
                )
            except requests.RequestException:
                pass

        return Response(
            MaterialRequestSerializer(instance).data,
            status=status.HTTP_200_OK,
        )


class MaterialRequestCreateView(generics.CreateAPIView):
    """
    Endpoint for Site B (Production Engineer) to submit requests.
    Uses API Key authentication instead of User session.
    """
    queryset = MaterialRequest.objects.all()
    serializer_class = MaterialRequestCreateSerializer
    permission_classes = [HasSiteBAPIKey]
    authentication_classes = []

    def perform_create(self, serializer):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        requester_email = serializer.validated_data.get("requester_email")
        
        # Look up User by requester_email. If not found, default to the first superuser (Admin)
        user = User.objects.filter(email=requester_email).first()
        if not user:
            user = User.objects.filter(is_superuser=True).first() or User.objects.filter(role="admin").first()

        # Update the owner/user of the Material if not already set
        material = serializer.validated_data.get("material")
        if material and not material.user and user:
            material.user = user
            material.save(update_fields=["user"])

        # Save request instance
        instance = serializer.save()

        # Webhook trigger: POST local id and status back to Site B
        if instance.webhook_url:
            payload = {
                "id": instance.id,
                "status": instance.status,
            }
            try:
                requests.post(
                    instance.webhook_url,
                    data=json.dumps(payload, separators=(",", ":")),
                    headers=_build_webhook_headers(payload),
                    timeout=5,
                )
            except requests.RequestException:
                pass


def _resolve_dead_stock_threshold(user):
    """Load threshold from user preferences; stored as days, exposed with display unit."""
    preference, _ = UserPreference.objects.get_or_create(user=user)
    threshold_days = preference.dead_stock_threshold_days or 30

    if threshold_days >= 30 and threshold_days % 30 == 0:
        threshold_value = threshold_days // 30
        threshold_unit = "months"
    else:
        threshold_value = threshold_days
        threshold_unit = "days"

    return threshold_days, threshold_value, threshold_unit


BASE_CURRENCY = Material.CURRENCY_EGP

# Static EGP conversion rates (extend FX_TO_EGP when adding currencies)
FX_TO_EGP = {
    Material.CURRENCY_EGP: 1.0,
    Material.CURRENCY_USD: 48.5,
    Material.CURRENCY_EUR: 52.0,
    Material.CURRENCY_SAR: 12.9,
    Material.CURRENCY_AED: 13.2,
}

_CURRENCY_BREAKDOWN_SYMBOL = {
    Material.CURRENCY_USD: "$",
    Material.CURRENCY_EUR: "€",
}


def _convert_to_egp(amount, currency):
    rate = FX_TO_EGP.get(currency, 1.0)
    return float(amount) * rate


def _aggregate_deadstock_capital(deadstock_list):
    """Sum capital tied-up by currency; return EGP total and display breakdown."""
    by_currency = {}
    for item in deadstock_list:
        currency = item.get("currency") or BASE_CURRENCY
        tied = float(item.get("capital_tied") or item.get("estimated_value") or 0)
        by_currency[currency] = by_currency.get(currency, 0.0) + tied

    total_egp = sum(_convert_to_egp(amount, cur) for cur, amount in by_currency.items())

    breakdown_parts = []
    for cur in (Material.CURRENCY_USD, Material.CURRENCY_EUR, Material.CURRENCY_SAR, Material.CURRENCY_AED):
        amount = by_currency.get(cur, 0.0)
        if amount <= 0:
            continue
        sym = _CURRENCY_BREAKDOWN_SYMBOL.get(cur)
        if sym:
            breakdown_parts.append(f"{sym}{amount:,.0f}")
        else:
            breakdown_parts.append(f"{amount:,.0f} {cur}")

    return total_egp, by_currency, " | ".join(breakdown_parts)


def _normalize_sparkline(values, count=5):
    """Scale arbitrary values to 8–100 for mini bar charts."""
    if not values:
        return [12, 20, 28, 36, 44]
    trimmed = list(values)[-count:]
    while len(trimmed) < count:
        trimmed.insert(0, trimmed[0] if trimmed else 0)
    peak = max(trimmed) or 1
    return [max(8, min(100, int((v / peak) * 100))) for v in trimmed]


def _build_weekly_out_totals(user, weeks=12):
    totals = []
    now = timezone.now()
    for i in range(weeks, 0, -1):
        start = now - timezone.timedelta(weeks=i)
        end = now - timezone.timedelta(weeks=i - 1)
        agg = (
            StockTransaction.objects.filter(
                material__user=user,
                type=StockTransaction.TYPE_OUT,
                created_at__gte=start,
                created_at__lt=end,
            ).aggregate(total=Sum("quantity"))
        )
        totals.append(float(agg["total"] or 0))
    return totals


class AIInsightsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            threshold_days, threshold_value, threshold_unit = _resolve_dead_stock_threshold(
                request.user
            )

            materials = Material.objects.filter(user=request.user, is_active=True)
            now = timezone.now()
            cutoff = now - timezone.timedelta(days=threshold_days)
            day_30 = now - timezone.timedelta(days=30)
            day_60 = now - timezone.timedelta(days=60)
            day_90 = now - timezone.timedelta(days=90)

            deadstock_list = []
            predictions_list = []

            for m in materials:
                # --- Dead Stock: qty > 0 and zero OUT transactions inside threshold window ---
                if float(m.current_quantity or 0) <= 0:
                    pass
                else:
                    has_out_in_window = m.transactions.filter(
                        type=StockTransaction.TYPE_OUT,
                        created_at__gte=cutoff,
                    ).exists()

                    if not has_out_in_window:
                        latest_out = (
                            m.transactions.filter(type=StockTransaction.TYPE_OUT)
                            .order_by("-created_at")
                            .first()
                        )
                        if latest_out and latest_out.created_at:
                            inactive_since = latest_out.created_at
                        elif m.created_at:
                            inactive_since = m.created_at
                        else:
                            inactive_since = now - timezone.timedelta(days=threshold_days)

                        delta = now - inactive_since
                        days_inactive = int(delta.total_seconds() // 86400)

                        if days_inactive < threshold_days:
                            continue

                        qty = float(m.current_quantity)
                        unit_cost = float(m.cost_price or 0)
                        capital_tied = qty * unit_cost

                        deadstock_list.append({
                            "material_id": m.id,
                            "sku": f"SKU-{m.id:04d}",
                            "material_name": m.name,
                            "last_out_date": (
                                latest_out.created_at.isoformat()
                                if latest_out and latest_out.created_at
                                else None
                            ),
                            "created_at": (
                                m.created_at.isoformat() if m.created_at else None
                            ),
                            "days_inactive": days_inactive,
                            "threshold_days": threshold_days,
                            "threshold_value": threshold_value,
                            "threshold_unit": threshold_unit,
                            "current_quantity": qty,
                            "cost_price": unit_cost,
                            "currency": m.currency,
                            "costing_method": m.costing_method,
                            "capital_tied": capital_tied,
                            "estimated_value": capital_tied,
                            "action_badge": (
                                "LIQUIDATE"
                                if days_inactive >= int(threshold_days * 1.5)
                                else "RELOCATE"
                            ),
                            "unit": m.unit,
                        })

                # --- Demand Prediction Logic ---
                transactions_out = list(m.transactions.filter(type=StockTransaction.TYPE_OUT, created_at__gte=day_90))
                
                qty_30 = sum(t.quantity for t in transactions_out if t.created_at and t.created_at >= day_30)
                qty_60 = sum(t.quantity for t in transactions_out if t.created_at and day_30 > t.created_at >= day_60)
                qty_90 = sum(t.quantity for t in transactions_out if t.created_at and day_60 > t.created_at >= day_90)

                adc_30 = float(qty_30) / 30.0
                adc_60 = float(qty_60) / 30.0
                adc_90 = float(qty_90) / 30.0

                prior_avg = (adc_60 + adc_90) / 2.0

                if prior_avg > 0:
                    change_pct = ((adc_30 - prior_avg) / prior_avg) * 100.0
                else:
                    change_pct = 100.0 if adc_30 > 0 else 0.0

                sku = f"SKU-{m.id:04d}"
                product_name = m.name

                if change_pct >= 10.0:
                    status_label = "increasing"
                    message = (
                        f"Demand for {sku} ({product_name}) has increased by "
                        f"{change_pct:.1f}% compared to prior averages."
                    )
                elif change_pct <= -10.0:
                    status_label = "decreasing"
                    message = (
                        f"Demand for {sku} ({product_name}) has decreased by "
                        f"{abs(change_pct):.1f}% compared to prior averages."
                    )
                else:
                    status_label = "stable"
                    message = (
                        f"Demand for {sku} ({product_name}) remains stable "
                        f"compared to prior averages."
                    )

                predictions_list.append({
                    "material_id": m.id,
                    "sku": sku,
                    "material_name": product_name,
                    "product_name": product_name,
                    "adc_30": adc_30,
                    "prior_avg": prior_avg,
                    "change_pct": change_pct,
                    "status": status_label,
                    "message": message,
                    "current_quantity": float(m.current_quantity) if m.current_quantity is not None else 0.0,
                    "max_quantity": float(m.max_quantity or 100),
                    "unit": m.unit,
                    "low_stock_threshold_percent": m.low_stock_threshold_percent or 30,
                })

            materials_list = list(materials)
            active_count = len(materials_list) or 1

            predicted_throughput = sum(p["adc_30"] * 30 for p in predictions_list)
            prior_throughput = sum(p["prior_avg"] * 30 for p in predictions_list)
            if prior_throughput > 0:
                throughput_trend_pct = (
                    (predicted_throughput - prior_throughput) / prior_throughput
                ) * 100.0
            else:
                throughput_trend_pct = 100.0 if predicted_throughput > 0 else 0.0

            critical_skus = 0
            for m in materials_list:
                max_qty = float(m.max_quantity or 100)
                if max_qty <= 0:
                    continue
                percent = (float(m.current_quantity) / max_qty) * 100.0
                threshold = m.low_stock_threshold_percent or 30
                if percent <= threshold:
                    critical_skus += 1

            est_stockout_risk = (critical_skus / active_count) * 100.0

            dead_stock_value, dead_stock_by_currency, dead_stock_breakdown = (
                _aggregate_deadstock_capital(deadstock_list)
            )

            accuracy_samples = []
            week_ago = now - timezone.timedelta(days=7)
            for p in predictions_list:
                predicted_week = p["adc_30"] * 7
                actual_week = float(
                    StockTransaction.objects.filter(
                        material_id=p["material_id"],
                        type=StockTransaction.TYPE_OUT,
                        created_at__gte=week_ago,
                    ).aggregate(total=Sum("quantity"))["total"]
                    or 0
                )
                if predicted_week <= 0 and actual_week <= 0:
                    accuracy_samples.append(100.0)
                    continue
                denom = max(actual_week, predicted_week, 1.0)
                error_ratio = abs(predicted_week - actual_week) / denom
                accuracy_samples.append(max(0.0, 100.0 - (error_ratio * 100.0)))

            ai_accuracy_rate = (
                sum(accuracy_samples) / len(accuracy_samples)
                if accuracy_samples
                else 94.0
            )

            weekly_out = _build_weekly_out_totals(request.user, weeks=12)
            throughput_weekly = [
                sum(
                    p["adc_30"] * 7
                    * (1 + (p["change_pct"] / 100.0) * (idx / 11))
                    for p in predictions_list
                )
                for idx in range(12)
            ]

            forecast_weeks = 13
            demand_forecast_points = []
            for w in range(forecast_weeks):
                week_total = 0.0
                for p in predictions_list:
                    growth = 1 + (p["change_pct"] / 100.0) * (w / max(forecast_weeks - 1, 1))
                    week_total += max(p["adc_30"] * 7 * growth, 0)
                point_date = (now + timezone.timedelta(weeks=w)).date().isoformat()
                demand_forecast_points.append({
                    "label": f"W{w + 1}",
                    "date": point_date,
                    "value": round(week_total, 2),
                })

            baseline_points = []
            for i, val in enumerate(weekly_out[-len(demand_forecast_points):]):
                baseline_points.append({
                    "label": demand_forecast_points[i]["label"],
                    "date": demand_forecast_points[i]["date"],
                    "value": round(val, 2),
                })
            if len(baseline_points) < len(demand_forecast_points):
                baseline_points = [
                    {"label": p["label"], "date": p["date"], "value": round(p["value"] * 0.85, 2)}
                    for p in demand_forecast_points
                ]

            seasonality_points = []
            for idx, val in enumerate(weekly_out):
                seasonality_points.append({
                    "label": f"W{idx + 1}",
                    "date": (now - timezone.timedelta(weeks=12 - idx)).date().isoformat(),
                    "value": round(val, 2),
                })

            def _peak_point(points, predictions_src):
                if not points:
                    return None
                peak = max(points, key=lambda x: x["value"])
                top_pred = max(predictions_src, key=lambda x: x["change_pct"], default=None)
                mid = top_pred["material_id"] if top_pred else None
                return {
                    "material_name": top_pred["material_name"] if top_pred else "Portfolio",
                    "sku": f"SKU-{mid:04d}" if mid else "PORTFOLIO",
                    "peak_date": peak["date"],
                    "required_capacity": round(peak["value"], 1),
                    "label": peak["label"],
                }

            forecast_peak = _peak_point(demand_forecast_points, predictions_list)
            seasonality_peak = _peak_point(seasonality_points, predictions_list)

            if ai_accuracy_rate >= 97:
                accuracy_tier = "PLATINUM"
            elif ai_accuracy_rate >= 90:
                accuracy_tier = "GOLD"
            elif ai_accuracy_rate >= 80:
                accuracy_tier = "SILVER"
            else:
                accuracy_tier = "CALIBRATING"

            if dead_stock_value > 15000:
                dead_stock_tier = "HIGH"
            elif dead_stock_value > 0:
                dead_stock_tier = "MEDIUM"
            else:
                dead_stock_tier = "NONE"

            return Response({
                "deadstock": deadstock_list,
                "dead_stock": deadstock_list,
                "predictions": predictions_list,
                "threshold_days": threshold_days,
                "threshold_value": threshold_value,
                "threshold_unit": threshold_unit,
                "metrics": {
                    "predicted_throughput": round(predicted_throughput, 1),
                    "throughput_trend_pct": round(throughput_trend_pct, 1),
                    "throughput_sparkline": _normalize_sparkline(throughput_weekly[-5:]),
                    "est_stockout_risk": round(est_stockout_risk, 1),
                    "critical_sku_count": critical_skus,
                    "stockout_bar_pct": round(est_stockout_risk, 1),
                    "dead_stock_value": round(dead_stock_value, 2),
                    "dead_stock_value_egp": round(dead_stock_value, 2),
                    "dead_stock_by_currency": {
                        k: round(v, 2) for k, v in dead_stock_by_currency.items()
                    },
                    "dead_stock_value_breakdown": dead_stock_breakdown,
                    "dead_stock_base_currency": BASE_CURRENCY,
                    "dead_stock_tier": dead_stock_tier,
                    "dead_stock_sparkline": _normalize_sparkline(
                        [item["current_quantity"] for item in deadstock_list] or [0]
                    ),
                    "ai_accuracy_rate": round(ai_accuracy_rate, 1),
                    "accuracy_bar_pct": round(ai_accuracy_rate, 1),
                    "accuracy_tier": accuracy_tier,
                    "accuracy_sparkline": _normalize_sparkline(accuracy_samples),
                    "dead_stock_bar_pct": round(
                        min(100.0, (dead_stock_value / 15000.0) * 100.0) if dead_stock_value else 0.0,
                        1,
                    ),
                },
                "charts": {
                    "demand_forecast": {
                        "points": demand_forecast_points,
                        "baseline": baseline_points,
                        "peak": forecast_peak,
                    },
                    "seasonality_trend": {
                        "points": seasonality_points,
                        "baseline": [],
                        "peak": seasonality_peak,
                    },
                },
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
