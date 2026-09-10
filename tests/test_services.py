import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime
from operations.models import Client, Machine, Part, ProductionOrder, WorkInProcess
from operations.services import close_production, start_production

@pytest.fixture
def data(db):
    client = Client.objects.create(code="TEST", name="Cliente")
    part = Part.objects.create(number="P-1", client=client, unit_weight_kg=Decimal("0.250"))
    employee = get_user_model().objects.create_user("operator")
    machine = Machine.objects.create(code="M-1")
    order = ProductionOrder.objects.create(folio="O01012026-1", program="S1", part=part,
        quantity=100, remaining_quantity=100)
    return order, machine, employee

@pytest.mark.django_db
def test_start_and_partial_close_preserve_balances(data):
    order, machine, employee = data
    work = start_production(order=order, machine=machine, quantity=40, employee=employee)
    order.refresh_from_db()
    assert order.remaining_quantity == 60
    close = close_production(work_item=work, quantity=15, employee=employee, comment="Parcial")
    work.refresh_from_db()
    order.refresh_from_db()
    assert work.remaining_quantity == 0
    assert work.status == WorkInProcess.Status.CLOSED
    assert order.remaining_quantity == 85
    assert order.status == ProductionOrder.Status.OPEN
    assert close.weight_kg == Decimal("3.750")

@pytest.mark.django_db
def test_machine_cannot_have_two_active_jobs(data):
    order, machine, employee = data
    start_production(order=order, machine=machine, quantity=20, employee=employee)
    with pytest.raises(ValidationError):
        start_production(order=order, machine=machine, quantity=10, employee=employee)

@pytest.mark.django_db
def test_cannot_close_more_than_remaining(data):
    order, machine, employee = data
    work = start_production(order=order, machine=machine, quantity=20, employee=employee)
    with pytest.raises(ValidationError):
        close_production(work_item=work, quantity=21, employee=employee)

@pytest.mark.django_db
def test_partial_close_can_release_machine_and_return_balance_to_order(data):
    order, machine, employee = data
    work = start_production(order=order, machine=machine, quantity=40, employee=employee)
    close = close_production(work_item=work, quantity=15, employee=employee,
                             comment="Cambio de pieza")
    work.refresh_from_db()
    order.refresh_from_db()
    assert close.quantity == Decimal("15")
    assert work.status == WorkInProcess.Status.CLOSED
    assert work.remaining_quantity == Decimal("0")
    assert order.remaining_quantity == Decimal("85")
    assert order.status == ProductionOrder.Status.OPEN

    replacement = start_production(order=order, machine=machine, quantity=20, employee=employee)
    assert replacement.machine_id == machine.pk

@pytest.mark.django_db
def test_release_full_quantity_does_not_reopen_order(data):
    order, machine, employee = data
    work = start_production(order=order, machine=machine, quantity=100, employee=employee)
    close_production(work_item=work, quantity=100, employee=employee)
    order.refresh_from_db()
    assert order.remaining_quantity == Decimal("0")
    assert order.status == ProductionOrder.Status.COMPLETE

@pytest.mark.django_db
def test_release_cannot_use_busy_or_invalid_work(data):
    order, machine, employee = data
    work = start_production(order=order, machine=machine, quantity=40, employee=employee)
    with pytest.raises(ValidationError):
        close_production(work_item=work, quantity=41, employee=employee)

@pytest.mark.django_db
def test_shift_changes_at_exactly_1636_local_time(data):
    order, machine, employee = data
    before = start_production(order=order, machine=machine, quantity=10, employee=employee)
    close_before = close_production(
        work_item=before, quantity=10, employee=employee,
        when=timezone.make_aware(datetime(2026, 9, 7, 16, 35, 59)))
    assert close_before.shift == "Turno A"

    second_machine = Machine.objects.create(code="M-2")
    second = start_production(order=order, machine=second_machine, quantity=10, employee=employee)
    close_at = close_production(
        work_item=second, quantity=10, employee=employee,
        when=timezone.make_aware(datetime(2026, 9, 7, 16, 36, 0)))
    assert close_at.shift == "Turno B"

@pytest.mark.django_db
def test_shift_a_starts_at_six_in_the_morning(data):
    order, machine, employee = data
    before = start_production(order=order, machine=machine, quantity=10, employee=employee)
    close_before = close_production(
        work_item=before, quantity=10, employee=employee,
        when=timezone.make_aware(datetime(2026, 9, 7, 5, 59, 59)))
    assert close_before.shift == "Turno B"

    second_machine = Machine.objects.create(code="M-2")
    second = start_production(order=order, machine=second_machine, quantity=10, employee=employee)
    close_at = close_production(
        work_item=second, quantity=10, employee=employee,
        when=timezone.make_aware(datetime(2026, 9, 7, 6, 0, 0)))
    assert close_at.shift == "Turno A"
