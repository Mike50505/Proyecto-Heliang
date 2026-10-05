from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from operations.models import Part, ProductionOrder


class FilteredOrderExportTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            "exporter", "exporter@example.com", "secret-pass")
        self.client.force_login(user)
        self.part_small = Part.objects.create(number="SMALL", diameter="3/8")
        self.part_large = Part.objects.create(number="LARGE", diameter="1/2")
        self.orders = [
            ProductionOrder.objects.create(
                folio="O-OPEN-A", program="W-A", part=self.part_large,
                quantity=10, remaining_quantity=10, priority=1,
                required_date=date(2026, 10, 8),
            ),
            ProductionOrder.objects.create(
                folio="O-COMPLETE", program="W-B", part=self.part_small,
                quantity=12, remaining_quantity=0,
                status=ProductionOrder.Status.COMPLETE,
                required_date=date(2026, 10, 9),
            ),
            ProductionOrder.objects.create(
                folio="O-OPEN-B", program="W-C", part=self.part_small,
                quantity=14, remaining_quantity=14, priority=2,
                required_date=date(2026, 10, 10),
            ),
        ]

    def rows(self, parameters=None):
        response = self.client.get(reverse("download-filtered-orders"), parameters or {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("ordenes_filtradas_", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        rows = list(workbook.active.values)
        workbook.close()
        return rows

    def test_no_filters_exports_all_orders_and_button_is_present(self):
        rows = self.rows()
        self.assertEqual([row[1] for row in rows[1:]],
                         ["O-OPEN-B", "O-COMPLETE", "O-OPEN-A"])
        page = self.client.get(reverse("order-list"))
        self.assertContains(page, "Descargar órdenes filtradas")

    def test_status_search_and_date_filters_match_screen(self):
        parameters = {
            "status": ProductionOrder.Status.OPEN,
            "q": "W-C", "start": "2026-10-09", "end": "2026-10-11",
        }
        page = self.client.get(reverse("order-list"), parameters)
        self.assertEqual([item.folio for item in page.context["orders"]], ["O-OPEN-B"])
        self.assertContains(page, "status=OPEN")
        rows = self.rows(parameters)
        self.assertEqual([row[1] for row in rows[1:]], ["O-OPEN-B"])

    def test_priority_filter_exports_only_priorities_in_diameter_order(self):
        parameters = {"priority": "1"}
        page = self.client.get(reverse("order-list"), parameters)
        expected = [item.folio for item in page.context["orders"]]
        rows = self.rows(parameters)
        self.assertEqual(expected, ["O-OPEN-B", "O-OPEN-A"])
        self.assertEqual([row[1] for row in rows[1:]], expected)
        self.assertIn("Diámetro", rows[0])
        self.assertEqual([row[2] for row in rows[1:]], [1, 1])

    def test_export_includes_all_matches_beyond_screen_limit(self):
        ProductionOrder.objects.bulk_create([
            ProductionOrder(
                folio=f"O-EXTRA-{index:03d}", program="W-EXTRA",
                part=self.part_large, quantity=1, remaining_quantity=1,
            )
            for index in range(500)
        ])
        page = self.client.get(reverse("order-list"))
        self.assertEqual(len(page.context["orders"]), 500)
        rows = self.rows()
        self.assertEqual(len(rows) - 1, 503)
