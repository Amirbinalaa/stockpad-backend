"""
Procurement & Planning Report API
Path: GET /api/reports/procurement-planning/

Performs all analytics server-side using batched / prefetched queries to
eliminate N+1 bottlenecks.  The response is a self-contained JSON payload
that the Vanilla JS client renders without any further back-end calls.
"""
from __future__ import annotations

import math
from datetime import timedelta

from django.db.models import Count, Max, Sum
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import Material, MaterialRequest, StockTransaction
from inventory.views import (
    _aggregate_deadstock_capital,
    _resolve_dead_stock_threshold,
)


# ---------------------------------------------------------------------------
# Status state machine constants
# ---------------------------------------------------------------------------
STATUS_CRITICAL     = "CRITICAL"
STATUS_NO_DATA      = "NO_DATA"
STATUS_REORDER_SOON = "REORDER_SOON"
STATUS_HEALTHY      = "HEALTHY"

AGING_ACTIVE    = "ACTIVE"
AGING_RELOCATE  = "RELOCATE"
AGING_LIQUIDATE = "LIQUIDATE"


def _compute_action_status(
    available_stock: float,
    days_left,           # int | None
    daily_usage,         # float | None
    reorder_point: float,
) -> str:
    """
    Strict priority state machine — order matters.

    1. CRITICAL  — available_stock <= 0  OR  days_left is not None and days_left <= 3
    2. NO DATA   — daily_usage is None   OR  daily_usage == 0
    3. REORDER SOON — (days_left is not None and days_left <= 14)
                      OR available_stock <= reorder_point
    4. HEALTHY   — everything else
    """
    if available_stock <= 0 or (days_left is not None and days_left <= 3):
        return STATUS_CRITICAL
    if daily_usage is None or daily_usage == 0:
        return STATUS_NO_DATA
    if (days_left is not None and days_left <= 14) or available_stock <= reorder_point:
        return STATUS_REORDER_SOON
    return STATUS_HEALTHY


def _compute_aging_metrics(
    *,
    current_stock: float,
    last_out_at,
    created_at,
    has_recent_out: bool,
    threshold_days: int,
    cost_price: float,
    currency: str,
    now,
) -> dict:
    """Derive idle-days, dead-stock flag, capital at risk, and recommended action."""
    if current_stock <= 0:
        return {
            "idle_days": None,
            "aging_action": AGING_ACTIVE,
            "is_dead_stock": False,
            "capital_at_risk": 0.0,
            "currency": currency,
        }

    if last_out_at:
        inactive_since = last_out_at
    elif created_at:
        inactive_since = created_at
    else:
        inactive_since = now - timedelta(days=threshold_days)

    idle_days = max(0, int((now - inactive_since).total_seconds() // 86400))

    if has_recent_out or idle_days < threshold_days:
        return {
            "idle_days": idle_days,
            "aging_action": AGING_ACTIVE,
            "is_dead_stock": False,
            "capital_at_risk": 0.0,
            "currency": currency,
        }

    capital_at_risk = current_stock * cost_price
    aging_action = (
        AGING_LIQUIDATE
        if idle_days >= int(threshold_days * 1.5)
        else AGING_RELOCATE
    )
    return {
        "idle_days": idle_days,
        "aging_action": aging_action,
        "is_dead_stock": True,
        "capital_at_risk": capital_at_risk,
        "currency": currency,
    }


def _empty_report_payload(threshold_days: int = 30) -> dict:
    return {
        "kpis": {
            "critical_count": 0,
            "reorder_count": 0,
            "blocked_products_count": 0,
            "healthy_count": 0,
            "dead_stock_value_egp": 0.0,
            "dead_stock_count": 0,
        },
        "executive_summary": {
            "critical_bottlenecks": [],
            "idle_stock_warnings": [],
        },
        "dead_stock_threshold_days": threshold_days,
        "categories": [],
        "materials": [],
    }


class ProcurementPlanningReportView(APIView):
    """
    Returns a pre-computed Procurement & Planning analytics payload for
    all active materials owned by the authenticated user.

    Performance contract:
      - One query for materials (with prefetch of BOM lines + products)
      - One aggregate query for allocated stock across all materials
      - One aggregate query for 30-day outflow transactions across all materials
      - One aggregate query for last OUT timestamp per material
      - One aggregate query for recent OUT activity inside dead-stock window
      - No per-material loops that touch the DB
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        threshold_days, _, _ = _resolve_dead_stock_threshold(user)
        cutoff = now - timedelta(days=threshold_days)

        # ── 1. Load all active materials + BOM lines in 3 queries (ORM join) ──
        materials = list(
            Material.objects
            .filter(user=user, is_active=True)
            .prefetch_related(
                "bom_lines__product",   # ProductMaterial → Product
            )
            .order_by("name")
        )
        if not materials:
            return Response(_empty_report_payload(threshold_days))

        material_ids = [m.id for m in materials]

        # ── 2. Batch: allocated stock per material ─────────────────────────────
        #   "Allocated" = sum of quantities from PENDING requests only.
        #   APPROVED requests already trigger Stock OUT (deducted from current
        #   stock), so including them here would double-deduct.
        allocated_qs = (
            MaterialRequest.objects
            .filter(
                material_id__in=material_ids,
                status=MaterialRequest.STATUS_PENDING,
            )
            .values("material_id")
            .annotate(total_allocated=Sum("quantity"))
        )
        allocated_map: dict[int, float] = {
            row["material_id"]: float(row["total_allocated"] or 0)
            for row in allocated_qs
        }

        # ── 3. Batch: 30-day outflow transactions per material ────────────────
        outflow_qs = (
            StockTransaction.objects
            .filter(
                material_id__in=material_ids,
                type=StockTransaction.TYPE_OUT,
                created_at__gte=thirty_days_ago,
            )
            .values("material_id")
            .annotate(
                total_out=Sum("quantity"),
                tx_count=Count("pk"),
            )
        )
        outflow_map: dict[int, dict] = {
            row["material_id"]: {
                "total_out": float(row["total_out"] or 0),
                "tx_count": int(row["tx_count"] or 0),
            }
            for row in outflow_qs
        }

        # ── 4. Batch: last OUT timestamp per material (dead-stock / idle days) ─
        last_out_qs = (
            StockTransaction.objects
            .filter(
                material_id__in=material_ids,
                type=StockTransaction.TYPE_OUT,
            )
            .values("material_id")
            .annotate(last_out_at=Max("created_at"))
        )
        last_out_map: dict[int, object] = {
            row["material_id"]: row["last_out_at"]
            for row in last_out_qs
        }

        recent_out_qs = (
            StockTransaction.objects
            .filter(
                material_id__in=material_ids,
                type=StockTransaction.TYPE_OUT,
                created_at__gte=cutoff,
            )
            .values("material_id")
            .annotate(recent_count=Count("pk"))
        )
        recent_out_set: set[int] = {
            row["material_id"]
            for row in recent_out_qs
            if row["recent_count"]
        }

        # ── 5. Per-material calculations (pure Python — no DB hits) ───────────
        result_rows = []
        categories: set[str] = set()
        deadstock_for_agg: list[dict] = []

        kpi_critical     = 0
        kpi_reorder      = 0   # CRITICAL + REORDER_SOON combined
        kpi_healthy      = 0
        blocked_products: set[int] = set()

        critical_bottlenecks: list[dict] = []
        idle_stock_warnings: list[dict] = []

        for mat in materials:
            current_stock  = float(mat.current_quantity or 0)
            reorder_point  = float(mat.reorder_point or 0)
            allocated      = allocated_map.get(mat.id, 0.0)
            available      = max(0.0, current_stock - allocated)

            # Category (derived from unit — mirrors serializers._UNIT_CATEGORY_MAP)
            category_name  = _unit_to_category(mat.unit)
            categories.add(category_name)

            # Burn rate (daily usage)
            out_data   = outflow_map.get(mat.id, {"total_out": 0.0, "tx_count": 0})
            total_out  = out_data["total_out"]
            tx_count   = out_data["tx_count"]

            if tx_count < 3:
                daily_usage = None
            else:
                daily_usage = total_out / 30.0

            # Days left
            if daily_usage is None or daily_usage == 0:
                days_left = None
            else:
                days_left = math.floor(available / daily_usage)

            # Action status
            action_status = _compute_action_status(
                available_stock=available,
                days_left=days_left,
                daily_usage=daily_usage,
                reorder_point=reorder_point,
            )

            # Dead stock / aging metrics
            aging = _compute_aging_metrics(
                current_stock=current_stock,
                last_out_at=last_out_map.get(mat.id),
                created_at=mat.created_at,
                has_recent_out=mat.id in recent_out_set,
                threshold_days=threshold_days,
                cost_price=float(mat.cost_price or 0),
                currency=mat.currency,
                now=now,
            )
            if aging["is_dead_stock"]:
                deadstock_for_agg.append({
                    "currency": aging["currency"],
                    "capital_tied": aging["capital_at_risk"],
                })
                idle_stock_warnings.append({
                    "material_id": mat.id,
                    "material_name": mat.name,
                    "idle_days": aging["idle_days"],
                    "aging_action": aging["aging_action"],
                    "capital_at_risk": aging["capital_at_risk"],
                    "currency": aging["currency"],
                })

            # KPI accumulation
            if action_status == STATUS_CRITICAL:
                kpi_critical += 1
                kpi_reorder  += 1
            elif action_status == STATUS_REORDER_SOON:
                kpi_reorder += 1
            elif action_status == STATUS_HEALTHY:
                kpi_healthy += 1

            # BOM — affected products & yield (already prefetched)
            affected_products = []
            for bom_line in mat.bom_lines.all():
                product = bom_line.product
                qty_per = float(bom_line.quantity_per_unit or 0)
                if qty_per > 0:
                    max_yield = math.floor(available / qty_per)
                else:
                    max_yield = 0

                affected_products.append({
                    "product_id":   product.id,
                    "product_name": product.name,
                    "sku":          product.sku,
                    "category":     product.category,
                    "qty_per_unit": qty_per,
                    "max_yield":    max_yield,
                })

                if action_status == STATUS_CRITICAL:
                    blocked_products.add(product.id)

            if action_status == STATUS_CRITICAL and affected_products:
                critical_bottlenecks.append({
                    "material_id": mat.id,
                    "material_name": mat.name,
                    "blocked_products": [
                        p["product_name"] for p in affected_products
                    ],
                })

            result_rows.append({
                "material_id":       mat.id,
                "material_name":     mat.name,
                "unit":              mat.unit,
                "category":          category_name,
                "current_stock":     current_stock,
                "allocated_stock":   allocated,
                "available_stock":   available,
                "reorder_point":     reorder_point,
                "daily_usage":       daily_usage,        # None → 'N/A' in UI
                "days_left":         days_left,          # None → 'N/A' in UI
                "idle_days":         aging["idle_days"],
                "aging_action":      aging["aging_action"],
                "is_dead_stock":     aging["is_dead_stock"],
                "capital_at_risk":   aging["capital_at_risk"],
                "action_status":     action_status,
                "affected_products": affected_products,
            })

        dead_stock_value_egp, _, dead_stock_breakdown = (
            _aggregate_deadstock_capital(deadstock_for_agg)
        )

        return Response({
            "kpis": {
                "critical_count":         kpi_critical,
                "reorder_count":          kpi_reorder,
                "blocked_products_count": len(blocked_products),
                "healthy_count":          kpi_healthy,
                "dead_stock_value_egp":   round(dead_stock_value_egp, 2),
                "dead_stock_count":       len(idle_stock_warnings),
                "dead_stock_breakdown":   dead_stock_breakdown,
            },
            "executive_summary": {
                "critical_bottlenecks": critical_bottlenecks,
                "idle_stock_warnings": idle_stock_warnings,
            },
            "dead_stock_threshold_days": threshold_days,
            "categories": sorted(categories),
            "materials":  result_rows,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_to_category(unit: str) -> str:
    """Mirror the unit→category mapping used in inventory serializers."""
    _MAP = {
        "kg": "Raw Materials",
        "L":  "Liquids & Chemicals",
        "pcs": "Components & Parts",
        "m":  "Structural Materials",
    }
    return _MAP.get(unit, "General Supplies")
