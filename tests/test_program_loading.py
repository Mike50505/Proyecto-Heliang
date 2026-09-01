from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from operations.models import Employee, Inventory, InventoryBucket, Movement, Part, Process, ProductionOrder
from operations.services import create_program_order, move_process_material, move_surplus


class ProgramLoadingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tester", password="test")
        self.employee = Employee.objects.create(payroll_number="100", name="Operador")

    def test_individual_load_creates_order_and_traceability(self):
        order = create_program_order(client_name="Cliente Uno", part_number="P-100",
                                     program="OP-55", quantity="25", employee=self.employee,
                                     comment="Urgente", user=self.user)
        self.assertEqual(order.remaining_quantity, Decimal("25"))
        self.assertEqual(order.part.client.name, "Cliente Uno")
        self.assertTrue(Movement.objects.filter(folio=order.folio,
                                                movement_type=Movement.Type.PROGRAM).exists())

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
