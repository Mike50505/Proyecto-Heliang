import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import datetime
from operations.models import (Client, Machine, Part, ProductionClose,
                               ProductionOrder, WorkInProcess)
from operations.services import (close_production, edit_production_order,
                                 next_folio, release_production, start_production)

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
def test_release_returns_remaining_pieces_without_creating_a_close(data):
    order, machine, employee = data
    work = start_production(order=order, machine=machine, quantity=40, employee=employee)
    released = release_production(work_item=work, user=employee)
    work.refresh_from_db()
    order.refresh_from_db()
    assert released == 40
    assert work.status == WorkInProcess.Status.CLOSED
    assert work.remaining_quantity == 0
    assert order.remaining_quantity == 100
    assert order.status == ProductionOrder.Status.OPEN
    assert not ProductionClose.objects.filter(work_item=work).exists()
    with pytest.raises(ValidationError):
        release_production(work_item=work, user=employee)


@pytest.mark.django_db
def test_start_and_close_reject_fractional_pieces(data):
    order, machine, employee = data
    with pytest.raises(ValidationError):
        start_production(order=order, machine=machine, quantity=Decimal("0.1"))
    work = start_production(order=order, machine=machine, quantity=10)
    with pytest.raises(ValidationError):
        close_production(work_item=work, quantity=Decimal("0.1"))

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
    order.refresh_from_db()
    assert order.status == ProductionOrder.Status.ALLOCATED
    close_production(work_item=work, quantity=100, employee=employee)
    order.refresh_from_db()
    assert order.remaining_quantity == Decimal("0")
    assert order.status == ProductionOrder.Status.COMPLETE


@pytest.mark.django_db
def test_database_rejects_two_active_jobs_for_one_machine(data):
    order, machine, employee = data
    start_production(order=order, machine=machine, quantity=20, employee=employee)
    other = ProductionOrder.objects.create(
        folio="O01012026-2", program="S2", part=order.part,
        quantity=10, remaining_quantity=10,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkInProcess.objects.create(
            folio="P-DUPLICATE", order=other, machine=machine,
            initial_quantity=10, remaining_quantity=10,
            started_at=timezone.now(), started_by=employee,
        )


@pytest.mark.django_db
def test_edit_revalidates_current_committed_quantity(data):
    order, machine, employee = data
    start_production(order=order, machine=machine, quantity=40, employee=employee)

    with pytest.raises(ValidationError):
        edit_production_order(
            order_id=order.pk, program=order.program, part=order.part,
            quantity=30, required_date=None, line="", priority=None,
            user=employee,
        )


@pytest.mark.django_db
def test_edit_cannot_change_part_after_production_started(data):
    order, machine, employee = data
    start_production(order=order, machine=machine, quantity=20, employee=employee)
    replacement = Part.objects.create(number="P-2")

    with pytest.raises(ValidationError):
        edit_production_order(
            order_id=order.pk, program=order.program, part=replacement,
            quantity=order.quantity, required_date=None, line="", priority=None,
            user=employee,
        )


@pytest.mark.django_db
def test_folio_counter_advances_for_production_and_close(data):
    when = timezone.now()
    production_folios = [next_folio(WorkInProcess, "P", when) for _ in range(2)]
    close_folios = [next_folio(ProductionClose, "C", when) for _ in range(2)]

    assert production_folios[0] != production_folios[1]
    assert close_folios[0] != close_folios[1]

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
