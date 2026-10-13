from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client as WebClient, RequestFactory
from django.urls import reverse
from django.utils import timezone

from operations.models import (
    AuditEvent, Client, Machine, Part, ProductionClose, ProductionOrder, WorkInProcess,
)
from operations.services import (
    close_production, delete_production_close, next_folio, start_production,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def case():
    user = get_user_model().objects.create_user("correction")
    access = user.module_access
    access.reports = access.reports_delete_closes = True
    access.save()
    customer = Client.objects.create(code="CORRECTION", name="Cliente")
    part = Part.objects.create(number="CORRECTION", client=customer, unit_weight_kg=Decimal("0.25"))
    machine = Machine.objects.create(code="CORRECTION")
    order = ProductionOrder.objects.create(
        folio="O-CORRECTION", program="S41", part=part, quantity=1,
        remaining_quantity=Decimal("0.9"), status=ProductionOrder.Status.OPEN)
    work = WorkInProcess.objects.create(
        folio="P-CORRECTION", order=order, machine=machine, initial_quantity=1,
        remaining_quantity=0, status=WorkInProcess.Status.CLOSED, started_at=timezone.now())
    close = ProductionClose.objects.create(
        folio="C-CORRECTION", work_item=work, quantity=Decimal("0.1"),
        weight_kg=Decimal("0.025"), closed_at=timezone.now(), closed_by=user, comment="Error original")
    return user, order, work, close


def test_fractional_close_deletion_restores_a_whole_piece_and_audit(case):
    user, order, work, close = case
    result = delete_production_close(close_id=close.pk, reason="Cantidad incorrecta", user=user)
    order.refresh_from_db()
    work.refresh_from_db()
    assert order.remaining_quantity == 1
    assert order.status == ProductionOrder.Status.OPEN
    assert work.status == WorkInProcess.Status.CLOSED
    assert work.remaining_quantity == 0
    assert not ProductionClose.objects.filter(pk=close.pk).exists()
    event = AuditEvent.objects.get(action="DELETE_PRODUCTION_CLOSE")
    assert event.user == user
    assert event.entity_id == close.folio
    assert event.data["quantity"] == "0.100"
    assert event.data["weight_kg"] == "0.0250"
    assert event.data["comment"] == "Error original"
    assert result["reason"] == "Cantidad incorrecta"
    new_work = start_production(order=order, machine=work.machine, quantity=1, user=user)
    corrected = close_production(work_item=new_work, quantity=1, user=user)
    assert corrected.weight_kg == Decimal("0.25")
    order.refresh_from_db()
    assert order.status == ProductionOrder.Status.COMPLETE


def test_legacy_active_process_recovers_fractional_balance(case):
    user, order, work, close = case
    order.remaining_quantity = 0
    order.status = ProductionOrder.Status.ALLOCATED
    order.save()
    work.remaining_quantity = Decimal("0.9")
    work.status = WorkInProcess.Status.ACTIVE
    work.save()
    result = delete_production_close(close_id=close.pk, reason="Corregir decimal", user=user)
    work.refresh_from_db()
    order.refresh_from_db()
    assert work.remaining_quantity == 1
    assert work.status == WorkInProcess.Status.ACTIVE
    assert order.remaining_quantity == 0
    assert result["returned_to"] == "work"
    close_production(work_item=work, quantity=1)
    order.refresh_from_db()
    assert order.status == ProductionOrder.Status.COMPLETE


def test_deleting_full_close_reopens_order_without_reactivating_machine(case):
    user, order, work, close = case
    order.remaining_quantity = 0
    order.status = ProductionOrder.Status.COMPLETE
    order.save()
    close.quantity = 1
    close.save()
    replacement_order = ProductionOrder.objects.create(
        folio="O-OTHER", program="OTHER", part=order.part, quantity=2, remaining_quantity=2)
    replacement = start_production(order=replacement_order, machine=work.machine, quantity=2)
    delete_production_close(close_id=close.pk, reason="Cierre equivocado", user=user)
    order.refresh_from_db()
    replacement.refresh_from_db()
    assert order.remaining_quantity == 1
    assert order.status == ProductionOrder.Status.OPEN
    assert replacement.status == WorkInProcess.Status.ACTIVE
    assert replacement.remaining_quantity == 2


@pytest.mark.parametrize("permission", ["reports", "reports_delete_closes"])
def test_permission_required_in_service_and_direct_endpoint(case, permission):
    user, order, work, close = case
    access = user.module_access
    setattr(access, permission, False)
    access.save()
    with pytest.raises(PermissionDenied):
        delete_production_close(close_id=close.pk, reason="Intento", user=user)
    web = WebClient()
    web.force_login(user)
    response = web.post(reverse("delete-close", args=[close.pk]), {"reason": "Intento"})
    assert response.status_code == 302
    assert ProductionClose.objects.filter(pk=close.pk).exists()
    order.refresh_from_db()
    assert order.remaining_quantity == Decimal("0.9")
    if permission == "reports_delete_closes":
        assert b"Eliminar cierre" not in web.get(reverse("report")).content


def test_confirmation_get_is_read_only_and_post_preserves_filters(case):
    user, order, work, close = case
    web = WebClient()
    web.force_login(user)
    url = reverse("delete-close", args=[close.pk]) + "?q=S41&shift=Turno+A"
    assert b"Eliminar cierre" in web.get(reverse("report")).content
    response = web.get(url)
    assert response.status_code == 200
    assert b"Confirmar eliminaci" in response.content
    assert ProductionClose.objects.filter(pk=close.pk).exists()
    response = web.post(url, {"reason": "Cantidad errónea"})
    assert response.status_code == 302
    assert response["Location"] == reverse("report") + "?q=S41&shift=Turno+A"
    assert not ProductionClose.objects.filter(pk=close.pk).exists()
    assert web.post(url, {"reason": "Repetido"}).status_code == 404
    order.refresh_from_db()
    assert order.remaining_quantity == 1
    assert AuditEvent.objects.filter(action="DELETE_PRODUCTION_CLOSE").count() == 1


def test_reason_and_csrf_are_required(case):
    user, order, work, close = case
    web = WebClient()
    web.force_login(user)
    url = reverse("delete-close", args=[close.pk])
    assert web.post(url, {"reason": "  "}).status_code == 200
    assert ProductionClose.objects.filter(pk=close.pk).exists()
    secure_web = WebClient(enforce_csrf_checks=True)
    secure_web.force_login(user)
    assert secure_web.post(url, {"reason": "Sin token"}).status_code == 403
    with pytest.raises(ValidationError):
        delete_production_close(close_id=close.pk, reason=" ", user=user)


def test_duplicate_service_deletion_does_not_return_pieces_twice(case):
    user, order, work, close = case
    delete_production_close(close_id=close.pk, reason="Error", user=user)
    with pytest.raises(ValidationError):
        delete_production_close(close_id=close.pk, reason="Otra vez", user=user)
    order.refresh_from_db()
    assert order.remaining_quantity == 1


def test_capacity_failure_rolls_back_deletion(case):
    user, order, work, close = case
    order.remaining_quantity = 0
    order.status = ProductionOrder.Status.COMPLETE
    order.save()
    ProductionOrder.objects.create(
        folio="O-CAPACITY", program="FULL", part=order.part,
        quantity=135000, remaining_quantity=135000)
    with pytest.raises(ValidationError, match="135000"):
        delete_production_close(close_id=close.pk, reason="Error", user=user)
    assert ProductionClose.objects.filter(pk=close.pk).exists()
    assert not AuditEvent.objects.filter(action="DELETE_PRODUCTION_CLOSE").exists()
    order.refresh_from_db()
    assert order.status == ProductionOrder.Status.COMPLETE
    assert order.remaining_quantity == 0


@pytest.mark.parametrize("active", [True, False])
def test_invalid_balance_rolls_back(case, active):
    user, order, work, close = case
    if active:
        work.status = WorkInProcess.Status.ACTIVE
        work.remaining_quantity = 1
        work.save()
    else:
        order.remaining_quantity = 1
        order.save()
    with pytest.raises(ValidationError):
        delete_production_close(close_id=close.pk, reason="Error", user=user)
    assert ProductionClose.objects.filter(pk=close.pk).exists()


def test_deleted_legacy_close_folio_is_not_reused(case):
    user, order, work, close = case
    moment = timezone.localtime()
    close.folio = "C" + moment.strftime("%d%m%Y") + "-1"
    close.save()
    delete_production_close(close_id=close.pk, reason="Error", user=user)
    assert next_folio(ProductionClose, "C", moment).endswith("-2")


def test_cancelled_order_cannot_receive_deleted_production(case):
    user, order, work, close = case
    order.status = ProductionOrder.Status.CANCELLED
    order.save()
    with pytest.raises(ValidationError, match="cancelada"):
        delete_production_close(close_id=close.pk, reason="Error", user=user)
    assert ProductionClose.objects.filter(pk=close.pk).exists()


def test_admin_cannot_bypass_balance_restoration(case):
    user, order, work, close = case
    request = RequestFactory().get("/admin/")
    request.user = get_user_model().objects.create_superuser("root")
    assert not admin.site._registry[ProductionClose].has_delete_permission(request, close)


def test_new_permission_is_opt_in_and_superuser_can_delete(case):
    user, order, work, close = case
    assert not get_user_model().objects.create_user("reader").module_access.reports_delete_closes
    root = get_user_model().objects.create_superuser("root")
    delete_production_close(close_id=close.pk, reason="Corrección administrativa", user=root)
    assert not ProductionClose.objects.filter(pk=close.pk).exists()
