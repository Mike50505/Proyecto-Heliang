from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from operations.models import Client, Machine, ModuleAccess, Part, ProductionOrder, WorkInProcess


class ClientFilterTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("filter-user", password="secret")
        access = ModuleAccess.objects.get(user=user)
        access.heliang = True
        access.program_loading = True
        access.save(update_fields=["heliang", "program_loading"])
        self.client.force_login(user)

        self.first_client = Client.objects.create(code="FIRST", name="Cliente Uno")
        self.second_client = Client.objects.create(code="SECOND", name="Cliente Dos")
        for index, customer in enumerate((self.first_client, self.second_client), 1):
            part = Part.objects.create(number=f"PART-{index}", client=customer)
            order = ProductionOrder.objects.create(
                folio=f"ORDER-{index}", program=f"PROGRAM-{index}", part=part,
                quantity=20, remaining_quantity=10,
            )
            machine = Machine.objects.create(code=f"MACHINE-{index}")
            WorkInProcess.objects.create(
                folio=f"WORK-{index}", order=order, machine=machine,
                initial_quantity=10, remaining_quantity=10, started_at=timezone.now(),
            )

    def test_order_list_and_download_filter_by_client(self):
        params = {"client": str(self.first_client.pk)}
        response = self.client.get(reverse("order-list"), params)
        self.assertEqual([order.folio for order in response.context["orders"]], ["ORDER-1"])
        self.assertContains(response, 'name="client"')
        self.assertContains(response, 'value="%s" selected' % self.first_client.pk)

        download = self.client.get(reverse("download-filtered-orders"), params)
        workbook = load_workbook(BytesIO(download.content), read_only=True)
        try:
            rows = list(workbook.active.values)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][1], "ORDER-1")
        finally:
            workbook.close()

    def test_heliang_filters_orders_and_work_independently(self):
        response = self.client.get(reverse("heliang"), {
            "order_client": str(self.first_client.pk),
            "work_client": str(self.second_client.pk),
        })
        self.assertEqual([order.folio for order in response.context["open_orders"]], ["ORDER-1"])
        self.assertEqual([work.folio for work in response.context["active_items"]], ["WORK-2"])
        self.assertEqual(len(response.context["machine_rows"]), 2)
        self.assertTrue(all(row["occupied"] for row in response.context["machine_rows"]))
        self.assertContains(response, 'name="order_client"')
        self.assertContains(response, 'name="work_client"')
