import re
from datetime import time
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import (AuditEvent, Client, Inventory, InventoryBucket, Movement, Part,
                     ProductionClose, ProductionOrder, WorkInProcess)


def next_folio(model, prefix, moment=None):
    moment = moment or timezone.localtime()
    date_key = moment.strftime("%d%m%Y")
    base = f"{prefix}{date_key}-"
    latest = model.objects.select_for_update().filter(folio__startswith=base).order_by("-id").first()
    sequence = 1
    if latest:
        match = re.search(r"-(\d+)$", latest.folio)
        sequence = int(match.group(1)) + 1 if match else latest.pk + 1
    candidate = f"{base}{sequence}"
    while model.objects.filter(folio=candidate).exists():
        sequence += 1
        candidate = f"{base}{sequence}"
    return candidate


@transaction.atomic
def create_program_order(*, client_name, part_number, program, quantity, employee=None,
                         required_date=None, line="", comment="", user=None):
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor que cero.")
    client_name = client_name.strip()
    client_code = re.sub(r"[^A-Z0-9]+", "-", client_name.upper()).strip("-")[:30] or "SIN-CLIENTE"
    client, _ = Client.objects.get_or_create(code=client_code, defaults={"name": client_name})
    part, _ = Part.objects.get_or_create(number=part_number.strip(), defaults={"client": client})
    if not part.client_id:
        part.client = client
        part.save(update_fields=["client", "updated_at"])
    order = ProductionOrder.objects.create(
        folio=next_folio(ProductionOrder, "O"), program=program.strip(), part=part,
        quantity=quantity, remaining_quantity=quantity, required_date=required_date,
        line=line.strip(), loaded_by=employee,
    )
    Movement.objects.create(
        folio=order.folio, movement_type=Movement.Type.PROGRAM, part=part,
        destination=program.strip(), program=program.strip(), quantity=quantity,
        occurred_at=timezone.now(), employee=employee, comment=comment.strip(),
    )
    AuditEvent.objects.create(user=user, action="LOAD_PROGRAM", entity="ProductionOrder",
                              entity_id=order.folio,
                              data={"program": order.program, "part": part.number,
                                    "quantity": str(quantity)})
    return order


@transaction.atomic
def move_surplus(*, part, action, quantity, employee=None, program="", comment="", user=None):
    quantity = Decimal(quantity)
    inventory, _ = Inventory.objects.select_for_update().get_or_create(part=part)
    if action == "ALLOCATE":
        if inventory.surplus < quantity:
            raise ValidationError("La cantidad supera el material sobrante disponible.")
        inventory.surplus -= quantity
        bucket, _ = InventoryBucket.objects.select_for_update().get_or_create(
            inventory=inventory, kind="PROGRAM", name=program.strip())
        bucket.quantity += quantity
        bucket.save(update_fields=["quantity", "updated_at"])
        source, destination = "Sobrante", program.strip()
    else:
        inventory.surplus += quantity
        inventory.real += quantity
        source, destination = "Producción", "Sobrante"
    inventory.save(update_fields=["surplus", "real", "updated_at"])
    movement = Movement.objects.create(
        folio=next_folio(Movement, "S"), movement_type=Movement.Type.SURPLUS,
        part=part, source=source, destination=destination, program=program.strip(),
        quantity=quantity, occurred_at=timezone.now(), employee=employee,
        comment=comment.strip())
    AuditEvent.objects.create(user=user, action="MOVE_SURPLUS", entity="Movement",
                              entity_id=str(movement.pk), data={"action": action,
                              "part": part.number, "quantity": str(quantity)})
    return movement


@transaction.atomic
def move_process_material(*, part, source_process, destination_process, program,
                          quantity, employee=None, comment="", user=None):
    quantity = Decimal(quantity)
    inventory, _ = Inventory.objects.select_for_update().get_or_create(part=part)
    source, _ = InventoryBucket.objects.select_for_update().get_or_create(
        inventory=inventory, kind="PROCESS", name=source_process.name)
    if source.quantity < quantity:
        raise ValidationError(
            f"{source_process.name} solo tiene {source.quantity} piezas disponibles para esta parte.")
    destination, _ = InventoryBucket.objects.select_for_update().get_or_create(
        inventory=inventory, kind="PROCESS", name=destination_process.name)
    source.quantity -= quantity
    destination.quantity += quantity
    source.save(update_fields=["quantity", "updated_at"])
    destination.save(update_fields=["quantity", "updated_at"])
    movement = Movement.objects.create(
        folio=next_folio(Movement, "M"), movement_type=Movement.Type.INVENTORY,
        part=part, source=source_process.name, destination=destination_process.name,
        program=program.strip(), quantity=quantity, occurred_at=timezone.now(),
        employee=employee, comment=comment.strip())
    AuditEvent.objects.create(user=user, action="MOVE_PROCESS_MATERIAL", entity="Movement",
                              entity_id=str(movement.pk), data={"part": part.number,
                              "source": source_process.name, "destination": destination_process.name,
                              "program": program.strip(), "quantity": str(quantity)})
    return movement


@transaction.atomic
def start_production(*, order, machine, quantity, employee=None, user=None, when=None):
    when = when or timezone.now()
    order = ProductionOrder.objects.select_for_update().get(pk=order.pk)
    quantity = Decimal(quantity)
    if order.status != ProductionOrder.Status.OPEN or quantity <= 0 or quantity > order.remaining_quantity:
        raise ValidationError("La cantidad debe ser positiva y no superar el saldo abierto.")
    if WorkInProcess.objects.select_for_update().filter(machine=machine, status=WorkInProcess.Status.ACTIVE).exists():
        raise ValidationError("La máquina seleccionada ya está ocupada.")
    work = WorkInProcess.objects.create(
        folio=next_folio(WorkInProcess, "P", when), order=order, machine=machine,
        initial_quantity=quantity, remaining_quantity=quantity, started_at=when, started_by=employee,
    )
    order.remaining_quantity -= quantity
    if order.remaining_quantity == 0:
        order.status = ProductionOrder.Status.COMPLETE
    order.save(update_fields=["remaining_quantity", "status", "updated_at"])
    AuditEvent.objects.create(user=user, action="START_PRODUCTION", entity="WorkInProcess", entity_id=work.folio,
        data={"order": order.folio, "machine": machine.code, "quantity": str(quantity)})
    return work


@transaction.atomic
def close_production(*, work_item, quantity, employee=None, user=None, comment="", when=None):
    when = when or timezone.now()
    work = WorkInProcess.objects.select_for_update().select_related("order__part").get(pk=work_item.pk)
    quantity = Decimal(quantity)
    if work.status != WorkInProcess.Status.ACTIVE or quantity <= 0 or quantity > work.remaining_quantity:
        raise ValidationError("La cantidad debe ser positiva y no superar el saldo en proceso.")
    local_time = timezone.localtime(when).time()
    shift = "Turno B" if local_time >= time(16, 36) else "Turno A"
    unit_weight = work.order.part.unit_weight_kg or Decimal("0")
    close = ProductionClose.objects.create(
        folio=next_folio(ProductionClose, "C", when), work_item=work, quantity=quantity,
        weight_kg=unit_weight * quantity, closed_at=when, shift=shift, comment=comment, closed_by=employee,
    )
    work.remaining_quantity -= quantity
    if work.remaining_quantity == 0:
        work.status = WorkInProcess.Status.CLOSED
    work.save(update_fields=["remaining_quantity", "status", "updated_at"])
    AuditEvent.objects.create(user=user, action="CLOSE_PRODUCTION", entity="ProductionClose", entity_id=close.folio,
        data={"work_item": work.folio, "quantity": str(quantity), "weight_kg": str(close.weight_kg)})
    return close
