from decimal import Decimal
from io import BytesIO
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from operations.models import (AuditEvent, Client, Inventory, InventoryBucket, Machine, Movement,
                               Part, Process, ProductionClose, ProductionOrder, WorkInProcess)
from operations.services import (create_program_order, move_process_material, move_surplus,
                                 resolve_program_client)


class ProgramLoadingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tester", password="test")
        self.employee = self.user

    def test_individual_load_creates_order_and_traceability(self):
        order = create_program_order(client_name="Cliente Uno", part_number="P-100",
                                     program="OP-55", quantity="25", employee=self.employee,
                                     comment="Urgente", user=self.user)
        self.assertEqual(order.remaining_quantity, Decimal("25"))
        self.assertEqual(order.part.client.name, "Cliente Uno")
        self.assertTrue(Movement.objects.filter(folio=order.folio,
                                                movement_type=Movement.Type.PROGRAM).exists())

    def test_downloaded_bulk_template_has_required_structure(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("download-program-template"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("plantilla_carga_programas.xlsx", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, ["Sheet1", "Instrucciones"])
        headers = [workbook["Sheet1"].cell(1, column).value for column in range(1, 8)]
        self.assertEqual(headers, ["ID Cliente", "Orden de Produccion", "Linea Prod Clte",
                                   "Fecha de Entrega", "Num. Parte", "Cantidad", "Linea"])

    def test_completed_programs_can_be_downloaded_as_excel(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        customer = Client.objects.create(
            code="LENNOX-1", name="LENNOX 1", external_id="CD0036")
        part = Part.objects.create(number="P-CLOSED", client=customer)
        closed_order = ProductionOrder.objects.create(
            folio="O-CLOSED", program="S35", part=part,
            quantity=100, remaining_quantity=0,
            status=ProductionOrder.Status.COMPLETE, line="L1",
        )
        machine = Machine.objects.create(code="M-CLOSED")
        work = WorkInProcess.objects.create(
            folio="P-CLOSED", order=closed_order, machine=machine,
            initial_quantity=100, remaining_quantity=0,
            status=WorkInProcess.Status.CLOSED, started_at=timezone.now(),
        )
        ProductionClose.objects.create(
            folio="C-CLOSED", work_item=work, quantity=100,
            closed_at=timezone.now(),
        )
        ProductionOrder.objects.create(
            folio="O-OPEN", program="S36", part=part,
            quantity=50, remaining_quantity=50,
            status=ProductionOrder.Status.OPEN,
        )

        response = self.client.get(reverse("download-completed-programs"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("programas_completados_", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        sheet = workbook["Programas completados"]
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual([sheet.cell(2, column).value for column in range(1, 9)], [
            "S35", "O-CLOSED", "CD0036", "LENNOX 1", "P-CLOSED", 100, 100, 0,
        ])

    def test_bulk_load_uses_original_line_column(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        expected_client = Client.objects.create(code="CLIENTE-UNO", name="Cliente Uno", external_id="ID001")
        Part.objects.create(number="P-200", client=expected_client)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sheet1"
        sheet.append(["ID Cliente", "Orden de Produccion", "Linea Prod Clte",
                      "Fecha de Entrega", "Num. Parte", "Cantidad", "Linea"])
        sheet.append(["ID001", "OP-200", "Cliente-L1", None, "P-200", 600, "LINEA-7"])
        sheet["F2"].number_format = "mm-dd-yy"
        output = BytesIO()
        workbook.save(output)
        upload = SimpleUploadedFile(
            "programas.xlsx", output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        response = self.client.post(reverse("bulk-load-program"), {
            "file": upload,
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ProductionOrder.objects.filter(program="OP-200").exists())
        response = self.client.post(reverse("bulk-load-program"), {
            "action": "confirm", "preview_token": response.context["preview_token"],
        })

        self.assertRedirects(response, reverse("order-list"))
        order = ProductionOrder.objects.get(program="OP-200")
        self.assertEqual(order.line, "LINEA-7")
        self.assertEqual(order.quantity, Decimal("600"))
        self.assertEqual(order.part.client, expected_client)

    def test_bulk_priority_follows_selection_order_instead_of_excel_order(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        customer = Client.objects.create(code="SELECTION", name="Selection", external_id="SEL")
        for existing in (False, True):
            with self.subTest(existing_priorities=existing):
                prefix = f"SEL-{existing}"
                part = Part.objects.create(number=prefix, client=customer)
                old_order = None
                if existing:
                    old_order = create_program_order(
                        client_name=customer.name, client=customer, part_number=prefix,
                        program="EXISTING", quantity="10", priority=1,
                    )
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = "Sheet1"
                sheet.append(["ID Cliente", "Orden de Produccion", "Linea Prod Clte",
                              "Fecha de Entrega", "Num. Parte", "Cantidad", "Linea"])
                for index in range(4):
                    sheet.append(["SEL", f"{prefix}-{index}", "", None, part.number, 10, "L1"])
                output = BytesIO()
                workbook.save(output)
                preview = self.client.post(reverse("bulk-load-program"), {
                    "file": SimpleUploadedFile("selection.xlsx", output.getvalue()),
                })
                self.assertEqual(preview.status_code, 200)
                response = self.client.post(reverse("bulk-load-program"), {
                    "action": "confirm", "preview_token": preview.context["preview_token"],
                    # Click Excel row 4 first, then row 2, then row 3. Row 5 is unselected.
                    "priority_check_4": "1", "priority_4": "1",
                    "priority_check_2": "1", "priority_2": "2",
                    "priority_check_3": "1", "priority_3": "3",
                })
                self.assertRedirects(response, reverse("order-list"))
                self.assertEqual(list(ProductionOrder.objects.filter(
                    program__startswith=prefix, priority__isnull=False,
                ).order_by("priority").values_list("program", "priority")), [
                    (f"{prefix}-2", 1), (f"{prefix}-0", 2), (f"{prefix}-1", 3),
                ])
                self.assertIsNone(ProductionOrder.objects.get(program=f"{prefix}-3").priority)
                if old_order:
                    old_order.refresh_from_db()
                    self.assertEqual(old_order.priority, 4)

    def test_client_resolution_falls_back_to_part_when_id_is_missing(self):
        expected_client = Client.objects.create(code="RHEEM-NIPLES", name="RHEEM NIPLES")
        Part.objects.create(number="82-TEST", client=expected_client)

        resolved = resolve_program_client(client_reference="#N/A", part_number="82-TEST")

        self.assertEqual(resolved, expected_client)

    def test_program_table_filters_by_search_and_status(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        part = Part.objects.create(number="FILTER-PART")
        ProductionOrder.objects.create(
            folio="FILTER-OPEN", program="S40", part=part,
            quantity=10, remaining_quantity=10,
        )
        ProductionOrder.objects.create(
            folio="FILTER-DONE", program="S41", part=part,
            quantity=10, remaining_quantity=0, status=ProductionOrder.Status.COMPLETE,
        )

        response = self.client.get(reverse("order-list"), {"q": "FILTER", "status": "OPEN"})

        self.assertContains(response, "FILTER-OPEN")
        self.assertNotContains(response, "FILTER-DONE")

    def test_priority_filter_groups_orders_by_diameter_then_priority(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        cases = [
            ("HALF-2", "1/2", 5),
            ("THREE-EIGHTHS-2", "C - 3/8", 4),
            ("HALF-1", "0.5", 2),
            ("THREE-EIGHTHS-1", "0.375", 1),
            ("THREE-EIGHTHS-3", "3/8", 7),
            ("NO-DIAMETER", "", 3),
            ("NOT-PRIORITY", "1/4", None),
        ]
        for folio, diameter, priority in cases:
            part = Part.objects.create(number=f"PART-{folio}", diameter=diameter)
            ProductionOrder.objects.create(
                folio=folio, program="S40", part=part,
                quantity=10, remaining_quantity=10, priority=priority,
            )

        response = self.client.get(reverse("order-list"), {"priority": "1"})
        orders = response.context["orders"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual([order.folio for order in orders], [
            "THREE-EIGHTHS-1", "THREE-EIGHTHS-2", "THREE-EIGHTHS-3",
            "HALF-1", "HALF-2", "NO-DIAMETER",
        ])
        self.assertEqual([order.priority for order in orders], [1, 4, 7, 2, 5, 3])
        self.assertEqual([order.diameter_priority for order in orders], [1, 2, 3, 1, 2, 1])
        self.assertContains(response, "<th>Diámetro</th>", html=True)
        self.assertContains(response, "diameter-group-heading", count=3)
        self.assertContains(response, "Diámetro 3/8")
        self.assertContains(response, "Diámetro 1/2")
        self.assertContains(response, "Diámetro Sin diámetro")
        self.assertContains(response, "3 órdenes", count=1)
        self.assertContains(response, "2 órdenes", count=1)
        self.assertContains(response, "1 orden", count=1)
        self.assertContains(response, 'name="order_ids"', count=6)
        self.assertContains(response, 'class="priority-badge"', count=6)
        self.assertContains(response, "priority-editor")
        self.assertContains(response, "priority_scope: 'diameter'")
        self.assertNotContains(response, "NOT-PRIORITY")

        unfiltered = self.client.get(reverse("order-list"))
        self.assertNotContains(unfiltered, "diameter-group-heading")
        self.assertContains(unfiltered, "priority-editor")

    def test_priority_filter_reorders_only_within_its_diameter(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        orders = {}
        for folio, diameter, priority in [
            ("A-1", "3/8", 1), ("B-1", "1/2", 2),
            ("A-2", "0.375", 3), ("B-2", "0.5", 4),
            ("A-3", "C - 3/8", 5),
        ]:
            part = Part.objects.create(number=f"PART-{folio}", diameter=diameter)
            orders[folio] = ProductionOrder.objects.create(
                folio=folio, program="S40", part=part,
                quantity=10, remaining_quantity=10, priority=priority,
            )

        response = self.client.post(reverse("update-order-priority", args=[orders["A-3"].pk]), {
            "priority_scope": "diameter", "priority": "1",
            "scope_ids": ",".join(str(orders[folio].pk) for folio in ("A-1", "A-2", "A-3")),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display"], "01")
        for order in orders.values():
            order.refresh_from_db()
        self.assertEqual({folio: order.priority for folio, order in orders.items()}, {
            "A-1": 3, "B-1": 2, "A-2": 5, "B-2": 4, "A-3": 1,
        })
        filtered = self.client.get(reverse("order-list"), {"priority": "1"})
        self.assertEqual(
            [(order.folio, order.diameter_priority) for order in filtered.context["orders"]],
            [("A-3", 1), ("A-1", 2), ("A-2", 3), ("B-1", 1), ("B-2", 2)],
        )
        self.assertTrue(AuditEvent.objects.filter(
            action="EDIT_PRIORITY", entity_id="A-3", data__scope="diameter").exists())

    def test_priority_filter_rejects_other_diameters_and_stale_order(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        parts = [Part.objects.create(number=f"P-{index}", diameter=diameter)
                 for index, diameter in enumerate(("3/8", "1/2", "3/8"), 1)]
        orders = [ProductionOrder.objects.create(
            folio=f"S-{index}", program="S40", part=part,
            quantity=10, remaining_quantity=10, priority=index,
        ) for index, part in enumerate(parts, 1)]
        url = reverse("update-order-priority", args=[orders[2].pk])
        for scope in ((orders[0].pk, orders[1].pk, orders[2].pk),
                      (orders[2].pk, orders[0].pk)):
            response = self.client.post(url, {
                "priority_scope": "diameter", "priority": "1",
                "scope_ids": ",".join(str(pk) for pk in scope),
            })
            self.assertEqual(response.status_code, 409)
        self.assertEqual(list(ProductionOrder.objects.order_by("pk").values_list(
            "priority", flat=True)), [1, 2, 3])

    def test_order_can_be_edited_and_recalculates_available_balance(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        part = Part.objects.create(number="EDIT-PART")
        order = ProductionOrder.objects.create(
            folio="EDIT-1", program="S40", part=part,
            quantity=100, remaining_quantity=60,
        )

        response = self.client.post(reverse("edit-order", args=[order.pk]), {
            "program": "S41", "part": part.pk, "quantity": 120,
            "required_date": "", "line": "L2",
        })

        self.assertRedirects(response, reverse("order-list"))
        order.refresh_from_db()
        self.assertEqual(order.program, "S41")
        self.assertEqual(order.remaining_quantity, Decimal("80"))

    def test_order_part_cannot_change_after_production_exists(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        original = Part.objects.create(number="EDIT-ORIGINAL")
        replacement = Part.objects.create(number="EDIT-REPLACEMENT")
        order = ProductionOrder.objects.create(
            folio="EDIT-PART-1", program="S40", part=original,
            quantity=100, remaining_quantity=60,
        )
        machine = Machine.objects.create(code="EDIT-MACHINE")
        WorkInProcess.objects.create(
            folio="EDIT-WORK", order=order, machine=machine,
            initial_quantity=40, remaining_quantity=40,
            started_at=timezone.now(),
        )

        response = self.client.post(reverse("edit-order", args=[order.pk]), {
            "program": "S40", "part": replacement.pk, "quantity": 100,
            "required_date": "", "line": "",
        })

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.part, original)
        self.assertContains(response, "No se puede cambiar la pieza")

    def test_order_deletion_is_confirmed_and_blocked_with_production(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        part = Part.objects.create(number="DELETE-PART")
        removable = ProductionOrder.objects.create(
            folio="DELETE-1", program="S42", part=part,
            quantity=10, remaining_quantity=10,
        )
        response = self.client.post(reverse("delete-order", args=[removable.pk]))
        self.assertRedirects(response, reverse("order-list"))
        self.assertFalse(ProductionOrder.objects.filter(pk=removable.pk).exists())

        protected = ProductionOrder.objects.create(
            folio="DELETE-2", program="S43", part=part,
            quantity=10, remaining_quantity=0,
        )
        machine = Machine.objects.create(code="DELETE-MACHINE")
        WorkInProcess.objects.create(
            folio="DELETE-WORK", order=protected, machine=machine,
            initial_quantity=10, remaining_quantity=10, started_at=timezone.now(),
        )
        self.client.post(reverse("delete-order", args=[protected.pk]))
        self.assertTrue(ProductionOrder.objects.filter(pk=protected.pk).exists())

    def test_bulk_delete_removes_selected_orders_with_one_request(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        part = Part.objects.create(number="BULK-DELETE-PART")
        removable = ProductionOrder.objects.create(
            folio="BULK-REMOVE", program="S50", part=part,
            quantity=10, remaining_quantity=10,
        )
        untouched = ProductionOrder.objects.create(
            folio="BULK-KEEP", program="S51", part=part,
            quantity=10, remaining_quantity=10,
        )
        protected = ProductionOrder.objects.create(
            folio="BULK-PROTECTED", program="S52", part=part,
            quantity=10, remaining_quantity=10,
        )
        machine = Machine.objects.create(code="BULK-MACHINE")
        WorkInProcess.objects.create(
            folio="BULK-WORK", order=protected, machine=machine,
            initial_quantity=10, remaining_quantity=10, started_at=timezone.now(),
        )
        Movement.objects.create(
            folio=removable.folio, movement_type=Movement.Type.PROGRAM,
            part=part, quantity=10, occurred_at=timezone.now(),
        )

        response = self.client.post(reverse("bulk-delete-orders"), {
            "order_ids": [removable.pk, protected.pk],
        }, follow=True)

        self.assertFalse(ProductionOrder.objects.filter(pk=removable.pk).exists())
        self.assertTrue(ProductionOrder.objects.filter(pk=protected.pk).exists())
        self.assertTrue(ProductionOrder.objects.filter(pk=untouched.pk).exists())
        self.assertFalse(Movement.objects.filter(folio="BULK-REMOVE").exists())
        self.assertTrue(AuditEvent.objects.filter(
            action="DELETE_PROGRAM", entity_id="BULK-REMOVE",
            data={"source": "bulk_selection"},
        ).exists())
        self.assertContains(response, "Se eliminaron 1 órdenes seleccionadas")
        self.assertContains(response, "No se eliminaron 1 órdenes")

    def test_order_list_has_visual_numbers_and_range_selection(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        part = Part.objects.create(number="NUMBERED-PART")
        ProductionOrder.objects.create(
            folio="NUMBERED-1", program="S53", part=part,
            quantity=10, remaining_quantity=10,
        )

        response = self.client.get(reverse("order-list"))

        self.assertContains(response, "Selección por filas")
        self.assertContains(response, 'data-row-number="1"')
        self.assertContains(response, 'aria-label="Seleccionar fila 1"')
        self.assertContains(response, "Seleccionar rango")

    def test_surplus_allocation_updates_both_balances(self):
        part = Part.objects.create(number="P-200")
        inventory = Inventory.objects.create(part=part, surplus=10, real=10)
        move_surplus(part=part, action="ALLOCATE", quantity=4, employee=self.employee,
                     program="OP-80", user=self.user)
        inventory.refresh_from_db()
        bucket = InventoryBucket.objects.get(inventory=inventory, kind="PROGRAM", name="OP-80")
        self.assertEqual(inventory.surplus, Decimal("6"))
        self.assertEqual(bucket.quantity, Decimal("4"))

    def test_surplus_cannot_become_negative(self):
        part = Part.objects.create(number="P-300")
        Inventory.objects.create(part=part, surplus=2, real=2)
        with self.assertRaises(ValidationError):
            move_surplus(part=part, action="ALLOCATE", quantity=3,
                         employee=self.employee, program="OP-90", user=self.user)
        self.assertFalse(Movement.objects.filter(part=part).exists())

    def test_material_moves_between_processes(self):
        part = Part.objects.create(number="P-400")
        inventory = Inventory.objects.create(part=part, real=12)
        cutting = Process.objects.create(code="corte", name="Corte", position=1)
        bending = Process.objects.create(code="doblez", name="Doblez", position=2)
        InventoryBucket.objects.create(inventory=inventory, kind="PROCESS", name="Corte", quantity=12)
        move_process_material(part=part, source_process=cutting, destination_process=bending,
                              program="OP-100", quantity=5, employee=self.employee, user=self.user)
        self.assertEqual(InventoryBucket.objects.get(inventory=inventory, name="Corte").quantity,
                         Decimal("7"))
        self.assertEqual(InventoryBucket.objects.get(inventory=inventory, name="Doblez").quantity,
                         Decimal("5"))
