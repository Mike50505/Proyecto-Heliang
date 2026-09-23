from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from operations.formatting import diameter_category, format_diameter_fraction
from operations.models import Client, ModuleAccess, Part, ProductionOrder


class DiameterFractionFormattingTests(SimpleTestCase):
    def test_converts_catalog_decimals_to_reduced_sixteenths(self):
        expected = {
            "0.25": "1/4",
            "0.3125": "5/16",
            "0.37": "3/8",
            "0.375": "3/8",
            "0.5": "1/2",
            "0.625": "5/8",
            "0.75": "3/4",
            "0.875": "7/8",
            "1.25": "1 1/4",
        }
        for value, fraction in expected.items():
            with self.subTest(value=value):
                self.assertEqual(format_diameter_fraction(value), fraction)

    def test_preserves_existing_fractions_and_descriptive_values(self):
        for value in ("7/8", "A - 3/8", "SOLDADURA 3/4", "7mm"):
            with self.subTest(value=value):
                self.assertEqual(format_diameter_fraction(value), value)

    def test_handles_empty_and_comma_decimal_values(self):
        self.assertEqual(format_diameter_fraction(None), "")
        self.assertEqual(format_diameter_fraction(""), "")
        self.assertEqual(format_diameter_fraction("0,625"), "5/8")

    def test_normalizes_prefixed_diameters_into_the_same_category(self):
        for value in ("1/2", "C-1/2", "C - 1/2", "A - 1/2", "SOLDADURA 1/2", "0.5"):
            with self.subTest(value=value):
                self.assertEqual(diameter_category(value), "1/2")


class HeliangDiameterDisplayTests(TestCase):
    def test_heliang_displays_decimal_diameter_as_fraction(self):
        user = get_user_model().objects.create_user("operator", password="secret")
        access = ModuleAccess.objects.get(user=user)
        access.heliang = True
        access.save(update_fields=["heliang"])
        customer = Client.objects.create(code="RAMOS", name="Ramos Arizpe")
        part = Part.objects.create(number="P-FRAC", client=customer, diameter="0.3125")
        ProductionOrder.objects.create(
            folio="O-FRAC", program="S40", part=part,
            quantity=100, remaining_quantity=100,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("heliang"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5/16")
        self.assertNotContains(response, "0.3125")

    def test_priority_sequence_restarts_for_each_normalized_diameter(self):
        user = get_user_model().objects.create_user("planner", password="secret")
        access = ModuleAccess.objects.get(user=user)
        access.heliang = True
        access.save(update_fields=["heliang"])
        customer = Client.objects.create(code="RAMOS-2", name="Ramos Arizpe")
        diameters = ("C - 1/2", "1/2", "0.375", "C-3/8", "5/8")
        for index, diameter in enumerate(diameters, 1):
            part = Part.objects.create(
                number=f"P-{index}", client=customer, diameter=diameter,
            )
            ProductionOrder.objects.create(
                folio=f"O-{index}", program="S41", part=part,
                quantity=100, remaining_quantity=100, priority=index,
            )
        self.client.force_login(user)

        response = self.client.get(reverse("heliang"))

        rows = response.context["priority_orders"]
        self.assertEqual(
            [(row.diameter_group, row.heliang_priority) for row in rows],
            [("3/8", 1), ("3/8", 2), ("1/2", 1), ("1/2", 2), ("5/8", 1)],
        )
        self.assertContains(response, "Prioridades por diámetro")
        self.assertContains(response, "Diámetro 3/8")
        self.assertContains(response, "Diámetro 1/2")
        self.assertContains(response, "2 órdenes", count=2)
        self.assertContains(response, "diameter-group-heading", count=3)
