from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from inventory.models import Material, MaterialRequest, Product, ProductMaterial, StockTransaction

User = get_user_model()


class ProcurementPlanningReportTestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="testmanager",
            email="manager@stockpad.io",
            password="Password123!",
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse("reports:procurement-planning")

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_catalog_returns_zero_kpis(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["kpis"]["critical_count"], 0)
        self.assertEqual(response.data["kpis"]["reorder_count"], 0)
        self.assertEqual(response.data["kpis"]["blocked_products_count"], 0)
        self.assertEqual(response.data["kpis"]["healthy_count"], 0)
        self.assertEqual(response.data["kpis"]["dead_stock_value_egp"], 0.0)
        self.assertEqual(response.data["kpis"]["dead_stock_count"], 0)
        self.assertEqual(response.data["executive_summary"]["critical_bottlenecks"], [])
        self.assertEqual(response.data["executive_summary"]["idle_stock_warnings"], [])
        self.assertEqual(response.data["materials"], [])

    def test_procurement_calculations_and_state_machine(self):
        # Material 1: Out of stock → CRITICAL state
        mat_critical = Material.objects.create(
            user=self.user,
            name="Steel Sheet",
            unit=Material.UNIT_KG,
            current_quantity=Decimal("0.00"),
            reorder_point=Decimal("10.00"),
        )

        # Material 2: Low transactions (< 3) → NO_DATA state
        mat_nodata = Material.objects.create(
            user=self.user,
            name="Copper Wire",
            unit=Material.UNIT_METER,
            current_quantity=Decimal("50.00"),
            reorder_point=Decimal("5.00"),
        )
        # Create only 2 outflow transactions
        for i in range(2):
            StockTransaction.objects.create(
                material=mat_nodata,
                type=StockTransaction.TYPE_OUT,
                quantity=Decimal("2.00"),
                performed_by=self.user,
            )

        # Material 3: Stock below reorder point → REORDER_SOON state
        mat_reorder = Material.objects.create(
            user=self.user,
            name="Aluminum Tube",
            unit=Material.UNIT_METER,
            current_quantity=Decimal("15.00"),
            reorder_point=Decimal("20.00"), # current 15 <= reorder_point 20
        )
        # Add 3 transactions so daily_usage is computed
        for i in range(3):
            StockTransaction.objects.create(
                material=mat_reorder,
                type=StockTransaction.TYPE_OUT,
                quantity=Decimal("1.00"),
                performed_by=self.user,
            )

        # Material 4: Ample stock → HEALTHY state
        mat_healthy = Material.objects.create(
            user=self.user,
            name="Plastic Resin",
            unit=Material.UNIT_KG,
            current_quantity=Decimal("500.00"),
            reorder_point=Decimal("50.00"),
        )
        for i in range(3):
            StockTransaction.objects.create(
                material=mat_healthy,
                type=StockTransaction.TYPE_OUT,
                quantity=Decimal("3.00"),
                performed_by=self.user,
            )

        # PENDING request counts toward allocated; APPROVED does not (Stock OUT
        # already reduced current_stock on approval).
        MaterialRequest.objects.create(
            material=mat_healthy,
            requester_id="eng_01",
            requester_email="engineer@siteb.com",
            quantity=Decimal("50.00"),
            status=MaterialRequest.STATUS_PENDING,
        )
        MaterialRequest.objects.create(
            material=mat_healthy,
            requester_id="eng_02",
            requester_email="engineer2@siteb.com",
            quantity=Decimal("30.00"),
            status=MaterialRequest.STATUS_APPROVED,
        )

        # Create a product connected to mat_critical via BOM
        product = Product.objects.create(
            name="Industrial Gearbox",
            sku="GB-900",
            category="Machinery",
            unit_of_measure="pcs",
        )
        ProductMaterial.objects.create(
            product=product,
            material=mat_critical,
            quantity_per_unit=Decimal("2.000"),
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        kpis = response.data["kpis"]
        self.assertEqual(kpis["critical_count"], 1)
        self.assertEqual(kpis["reorder_count"], 2) # critical + reorder_soon
        self.assertEqual(kpis["blocked_products_count"], 1) # relies on mat_critical
        self.assertEqual(kpis["healthy_count"], 1)

        materials_by_name = {m["material_name"]: m for m in response.data["materials"]}

        # Verify Steel Sheet (Critical)
        steel = materials_by_name["Steel Sheet"]
        self.assertEqual(steel["action_status"], "CRITICAL")
        self.assertEqual(steel["available_stock"], 0.0)
        self.assertEqual(len(steel["affected_products"]), 1)
        self.assertEqual(steel["affected_products"][0]["max_yield"], 0)

        # Verify Copper Wire (No Data due to < 3 transactions)
        copper = materials_by_name["Copper Wire"]
        self.assertEqual(copper["action_status"], "NO_DATA")
        self.assertIsNone(copper["daily_usage"])
        self.assertIsNone(copper["days_left"])

        # Verify Aluminum Tube (Reorder Soon)
        aluminum = materials_by_name["Aluminum Tube"]
        self.assertEqual(aluminum["action_status"], "REORDER_SOON")

        # Verify Plastic Resin (Healthy — only PENDING counts as allocated)
        resin = materials_by_name["Plastic Resin"]
        self.assertEqual(resin["action_status"], "HEALTHY")
        self.assertEqual(resin["current_stock"], 500.0)
        self.assertEqual(resin["allocated_stock"], 50.0)
        self.assertEqual(resin["available_stock"], 450.0)
        self.assertEqual(resin["aging_action"], "ACTIVE")
        self.assertFalse(resin["is_dead_stock"])

        self.assertIn("executive_summary", response.data)
        self.assertEqual(len(response.data["executive_summary"]["critical_bottlenecks"]), 1)

    def test_dead_stock_metrics_and_executive_summary(self):
        """Idle stock beyond threshold surfaces RELOCATE/LIQUIDATE and capital at risk."""
        mat_idle = Material.objects.create(
            user=self.user,
            name="Stale Resin Drum",
            unit=Material.UNIT_KG,
            current_quantity=Decimal("100.00"),
            cost_price=Decimal("765.00"),
            currency=Material.CURRENCY_EGP,
        )
        old_out_date = timezone.now() - timedelta(days=40)
        tx = StockTransaction.objects.create(
            material=mat_idle,
            type=StockTransaction.TYPE_OUT,
            quantity=Decimal("1.00"),
            performed_by=self.user,
        )
        StockTransaction.objects.filter(pk=tx.pk).update(created_at=old_out_date)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        row = next(m for m in response.data["materials"] if m["material_name"] == "Stale Resin Drum")
        self.assertTrue(row["is_dead_stock"])
        self.assertEqual(row["aging_action"], "RELOCATE")
        self.assertGreaterEqual(row["idle_days"], 40)
        self.assertEqual(row["capital_at_risk"], 76500.0)

        kpis = response.data["kpis"]
        self.assertEqual(kpis["dead_stock_count"], 1)
        self.assertEqual(kpis["dead_stock_value_egp"], 76500.0)

        idle_warnings = response.data["executive_summary"]["idle_stock_warnings"]
        self.assertEqual(len(idle_warnings), 1)
        self.assertEqual(idle_warnings[0]["material_name"], "Stale Resin Drum")
        self.assertEqual(idle_warnings[0]["aging_action"], "RELOCATE")

    def test_uncategorized_materials_infer_category_in_report(self):
        Material.objects.create(
            user=self.user,
            name="Portland Cement",
            unit=Material.UNIT_KG,
            current_quantity=Decimal("50.00"),
        )
        Material.objects.create(
            user=self.user,
            name="Hex Bolts",
            unit=Material.UNIT_PCS,
            current_quantity=Decimal("200.00"),
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        by_name = {row["material_name"]: row for row in response.data["materials"]}
        self.assertEqual(by_name["Portland Cement"]["category"], "Building Materials")
        self.assertEqual(by_name["Hex Bolts"]["category"], "Steel & Metal")
        self.assertIn("Building Materials", response.data["categories"])
        self.assertIn("Steel & Metal", response.data["categories"])


from reports.procurement_report_html import render_category_badge_html


class ProcurementReportHtmlTests(TestCase):
    def test_category_badge_renders_svg_and_styles(self):
        html = render_category_badge_html("Building Materials")
        self.assertIn('class="category-badge"', html)
        self.assertIn('width="12"', html)
        self.assertIn('height="12"', html)
        self.assertIn("Building Materials", html)
