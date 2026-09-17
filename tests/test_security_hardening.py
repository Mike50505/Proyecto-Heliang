from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from operations.models import Client, ModuleAccess, Part, ProductionOrder
from operations.security import spreadsheet_safe
from operations.services import create_program_order


class SecurityHardeningTests(TestCase):
    def test_new_user_has_no_universe_permissions(self):
        user = get_user_model().objects.create_user("least-privilege", password="secret-pass")
        access = ModuleAccess.objects.get(user=user)
        self.assertFalse(access.universe)
        self.assertFalse(access.universe_edit)
        self.assertFalse(access.universe_import)

    def test_read_only_universe_user_cannot_add_parts(self):
        user = get_user_model().objects.create_user("reader", password="secret-pass")
        access = ModuleAccess.objects.get(user=user)
        access.universe = True
        access.save(update_fields=["universe"])
        self.client.force_login(user)

        response = self.client.post(reverse("universe"), {
            "action": "add", "number": "UNAUTHORIZED-PART",
            "description": "", "client": "", "diameter": "", "unit_weight_kg": "",
        })

        self.assertRedirects(response, reverse("universe"))
        self.assertFalse(Part.objects.filter(number="UNAUTHORIZED-PART").exists())

    def test_existing_part_cannot_be_reassigned_while_loading_order(self):
        original = Client.objects.create(code="ORIGINAL", name="Original")
        other = Client.objects.create(code="OTHER", name="Other")
        part = Part.objects.create(number="LOCKED-PART", client=original)

        with self.assertRaises(ValidationError):
            create_program_order(
                client_name=other.name, client=other, part_number=part.number,
                program="S1", quantity=Decimal("10"),
            )
        part.refresh_from_db()
        self.assertEqual(part.client, original)

    def test_spreadsheet_formula_prefixes_are_neutralized(self):
        for value in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tformula", "\rformula"):
            self.assertTrue(spreadsheet_safe(value).startswith("'"))
        self.assertEqual(spreadsheet_safe("normal"), "normal")

    def test_allocated_order_is_not_exported_as_completed(self):
        user = get_user_model().objects.create_superuser("exporter", password="secret-pass")
        self.client.force_login(user)
        part = Part.objects.create(number="ALLOCATED-PART")
        ProductionOrder.objects.create(
            folio="ALLOCATED-1", program="S1", part=part,
            quantity=10, remaining_quantity=0,
            status=ProductionOrder.Status.ALLOCATED,
        )

        response = self.client.get(reverse("download-completed-programs"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"ALLOCATED-1", response.content)

    def test_login_is_throttled_after_five_failures(self):
        get_user_model().objects.create_user("limited", password="correct-password")
        url = reverse("login")
        for _ in range(5):
            self.client.post(url, {"username": "limited", "password": "wrong-password"})

        response = self.client.post(
            url, {"username": "limited", "password": "correct-password"})

        self.assertContains(response, "Demasiados intentos", status_code=200)
