from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from operations.models import AuditEvent, Client, Part, ProductionOrder, ProgramImportReceipt
from operations.services import create_program_order


class ImportRepetitionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("importer", password="test")
        self.client.force_login(self.user)
        self.customer = Client.objects.create(code="C", name="Client", external_id="C")
        Part.objects.create(number="P", client=self.customer)

    def upload(self, rows, confirm=True):
        workbook = Workbook()
        workbook.active.append(["ID Cliente", "Orden de Produccion", "Linea Prod Clte",
                                "Fecha de Entrega", "Num. Parte", "Cantidad", "Linea"])
        for row in rows:
            if row is None:
                workbook.active.append([None] * 7)
            else:
                program, quantity, required = row
                workbook.active.append(["C", program, "L1", required, "P", quantity, "L1"])
        output = BytesIO()
        workbook.save(output)
        response = self.client.post(reverse("bulk-load-program"), {
            "file": SimpleUploadedFile("load.xlsx", output.getvalue())})
        if confirm and response.context and response.context.get("preview_token"):
            return self.confirm(response.context["preview_token"])
        return response

    def confirm(self, token):
        return self.client.post(reverse("bulk-load-program"), {
            "action": "confirm", "preview_token": token})

    def test_preview_preserves_repeated_rows_without_writes(self):
        response = self.upload([("A", 10, None)] * 2, confirm=False)
        self.assertContains(response, "Confirmar carga")
        self.assertEqual(response.context["preview_added"], 2)
        self.assertFalse(ProductionOrder.objects.exists())
        self.assertFalse(ProgramImportReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_repeated_file_and_rows_are_new_orders(self):
        for _ in range(2):
            self.assertEqual(self.upload([("A", 10, None)] * 2).status_code, 302)
        self.assertEqual(ProductionOrder.objects.count(), 4)
        self.assertEqual(ProductionOrder.objects.values("folio").distinct().count(), 4)

    def test_same_confirmation_is_only_applied_once(self):
        preview = self.upload([("A", 10, None)], confirm=False)
        self.upload([("A", 10, None)])
        for _ in range(2):
            self.confirm(preview.context["preview_token"])
        self.assertEqual(ProductionOrder.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action="BULK_IMPORT_RESULT").count(), 2)

    def test_deleted_order_absent_from_file_stays_deleted(self):
        self.upload([("OLD", 10, None)])
        old = ProductionOrder.objects.get()
        self.client.post(reverse("delete-order", args=[old.pk]))
        self.upload([("NEW", 10, None)])
        self.assertFalse(ProductionOrder.objects.filter(program="OLD").exists())
        self.assertNotEqual(ProductionOrder.objects.get().folio, old.folio)

    def test_new_identical_order_does_not_reuse_deleted_folio(self):
        self.upload([("A", 10, None)])
        old = ProductionOrder.objects.get()
        self.client.post(reverse("bulk-delete-orders"), {"order_ids": [old.pk]})
        self.upload([("A", 10, None)])
        self.assertEqual(ProductionOrder.objects.count(), 1)
        self.assertNotEqual(ProductionOrder.objects.get().folio, old.folio)
        self.assertTrue(AuditEvent.objects.filter(action="DELETE_PROGRAM", entity_id=old.folio).exists())

    def test_historical_content_receipts_do_not_block_new_loads(self):
        from operations.import_identity import program_fingerprint
        for legacy in (True, False):
            ProgramImportReceipt.objects.create(fingerprint=program_fingerprint(
                program="A", part_number="P", quantity=10, client_id=self.customer.pk,
                line="L1", legacy=legacy))
        self.upload([("A", 10, None)])
        self.assertEqual(ProductionOrder.objects.count(), 1)

    def test_rows_below_blank_gap_are_visible_in_preview(self):
        rows = [("A", 10, None)] * 12 + [None] * 47 + [("B", 20, None)] * 54
        response = self.upload(rows, confirm=False)
        self.assertEqual(response.context["preview_added"], 66)
        self.assertEqual(response.context["preview"][12]["row_number"], 61)
        self.confirm(response.context["preview_token"])
        self.assertEqual(ProductionOrder.objects.count(), 66)

    def test_invalid_or_other_user_token_cannot_import(self):
        response = self.upload([("A", 10, None)], confirm=False)
        token = response.context["preview_token"]
        self.confirm(token + "bad")
        other = get_user_model().objects.create_superuser("other", password="test")
        self.client.force_login(other)
        self.confirm(token)
        self.assertFalse(ProductionOrder.objects.exists())

    def test_errors_prevent_confirmation(self):
        response = self.upload([("A", 10, None), ("B", -1, None)], confirm=False)
        self.assertFalse(response.context["preview_token"])
        self.assertNotContains(response, "Confirmar carga")
        self.assertFalse(ProgramImportReceipt.objects.exists())

    def test_expired_preview_cannot_import(self):
        with patch("django.core.signing.time.time", return_value=1800000000):
            response = self.upload([("A", 10, None)], confirm=False)
        with patch("django.core.signing.time.time", return_value=1800001801):
            result = self.confirm(response.context["preview_token"])
        self.assertContains(result, "La vista previa venció")
        self.assertFalse(ProductionOrder.objects.exists())

    def test_failed_confirmation_rolls_back_and_can_be_retried(self):
        response = self.upload([("A", 10, None), ("B", 20, None)], confirm=False)
        token = response.context["preview_token"]

        def fail_second(**kwargs):
            if kwargs["program"] == "B":
                raise ValidationError("Error simulado")
            return create_program_order(**kwargs)

        with patch("operations.views.create_program_order", side_effect=fail_second):
            result = self.confirm(token)
        self.assertContains(result, "Error simulado")
        self.assertFalse(ProductionOrder.objects.exists())
        self.assertFalse(ProgramImportReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
        self.confirm(token)
        self.assertEqual(ProductionOrder.objects.count(), 2)