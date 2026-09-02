import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
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
    assert work.remaining_quantity == 25
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
