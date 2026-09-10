import re
from datetime import time
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from hashlib import sha256
from .models import (AuditEvent, Client, Inventory, InventoryBucket, Movement, Part,
                     ProductionClose, ProductionOrder, WorkInProcess, ProgramImportReceipt)

SHIFT_B_START = time(16, 36)
SHIFT_A_START = time(6, 0)


@transaction.atomic
def next_folio(model, prefix, moment=None):
    moment = moment or timezone.localtime()
    date_key = moment.strftime("%d%m%Y")
    base = f"{prefix}{date_key}-"
    historical_folios = set()
    if model is ProductionOrder:
        # Serialize allocation until the caller's order transaction commits.
        lock_key = sha256(f"folio-lock:{base}".encode()).hexdigest()
        ProgramImportReceipt.objects.get_or_create(fingerprint=lock_key)
        ProgramImportReceipt.objects.select_for_update().get(fingerprint=lock_key)
        historical_folios = set(AuditEvent.objects.filter(
            entity="ProductionOrder", entity_id__startswith=base
        ).values_list("entity_id", flat=True))
    latest = model.objects.select_for_update().filter(folio__startswith=base).order_by("-id").first()
    sequence = 1
    if latest:
        match = re.search(r"-(\d+)$", latest.folio)
        sequence = int(match.group(1)) + 1 if match else latest.pk + 1
    for folio in historical_folios:
        suffix = folio[len(base):]
        if suffix.isdigit():
            sequence = max(sequence, int(suffix) + 1)
    candidate = f"{base}{sequence}"
    while model.objects.filter(folio=candidate).exists():
        sequence += 1
        candidate = f"{base}{sequence}"
    return candidate


def resolve_program_client(*, client_reference, part_number):
    reference = client_reference.strip()
    part_number = part_number.strip()
    part = Part.objects.select_related("client").filter(number=part_number).first()
    mapped_client = part.client if part else None

    if reference and reference.upper() not in {"#N/A", "N/A", "NA"}:
        candidates = Client.objects.filter(external_id__iexact=reference)
        if mapped_client and candidates.filter(pk=mapped_client.pk).exists():
            return mapped_client
        if candidates.count() == 1:
            return candidates.first()
        direct = Client.objects.filter(code__iexact=reference).first()
        if direct:
            return direct

    if mapped_client:
        return mapped_client

    raise ValidationError(
        f"No se encontró un cliente para el ID '{reference or 'vacío'}' "
        f"ni para el número de parte '{part_number}'."
    )


@transaction.atomic
def create_program_order(*, client_name, part_number, program, quantity, employee=None,
                         required_date=None, line="", priority=None, comment="", user=None, client=None):
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor que cero.")
    if priority is not None and int(priority) < 1:
        raise ValidationError("La prioridad debe ser un entero mayor que cero.")
    client_name = client_name.strip()
    if client is None:
        client_code = re.sub(r"[^A-Z0-9]+", "-", client_name.upper()).strip("-")[:30] or "SIN-CLIENTE"
        client, _ = Client.objects.get_or_create(code=client_code, defaults={"name": client_name})
    part, _ = Part.objects.get_or_create(number=part_number.strip(), defaults={"client": client})
    if part.client_id != client.pk:
        part.client = client
        part.save(update_fields=["client", "updated_at"])
    if priority is not None:
        ProductionOrder.objects.select_for_update().filter(priority__gte=int(priority)).update(priority=F("priority") + 1)
    order = ProductionOrder.objects.create(
        folio=next_folio(ProductionOrder, "O"), program=program.strip(), part=part,
        quantity=quantity, remaining_quantity=quantity, required_date=required_date,
        line=line.strip(), priority=priority, loaded_by=employee,
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
    if priority is not None:
        normalize_priorities()
    return order


@transaction.atomic
def normalize_priorities():
    prioritized = list(ProductionOrder.objects.select_for_update().filter(
        priority__isnull=False).order_by("priority", "id"))
    for number, item in enumerate(prioritized, 1):
        if item.priority != number:
            ProductionOrder.objects.filter(pk=item.pk).update(priority=number)


@transaction.atomic
def set_production_order_priority(*, order, priority, user=None):
    if priority is not None and int(priority) < 1:
        raise ValidationError("La prioridad debe ser un entero mayor que cero.")
    current = ProductionOrder.objects.select_for_update().get(pk=order.pk)
    old = current.priority
    priority = int(priority) if priority is not None else None
    if old == priority:
        return current
    if old is None and priority is not None:
        ProductionOrder.objects.select_for_update().filter(priority__gte=priority).exclude(pk=current.pk).update(priority=F("priority") + 1)
    elif old is not None and priority is None:
        ProductionOrder.objects.select_for_update().filter(priority__gt=old).update(priority=F("priority") - 1)
    elif old is not None and priority is not None:
        if priority < old:
            ProductionOrder.objects.select_for_update().filter(priority__gte=priority, priority__lt=old).exclude(pk=current.pk).update(priority=F("priority") + 1)
        elif priority > old:
            ProductionOrder.objects.select_for_update().filter(priority__gt=old, priority__lte=priority).exclude(pk=current.pk).update(priority=F("priority") - 1)
    current.priority = priority
    current.save(update_fields=["priority", "updated_at"])
    normalize_priorities()
    AuditEvent.objects.create(user=user, action="EDIT_PRIORITY", entity="ProductionOrder",
                              entity_id=current.folio, data={"priority": priority, "previous": old})
    return current


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
    shift = "Turno A" if SHIFT_A_START <= local_time < SHIFT_B_START else "Turno B"
    unit_weight = work.order.part.unit_weight_kg or Decimal("0")
    close = ProductionClose.objects.create(
        folio=next_folio(ProductionClose, "C", when), work_item=work, quantity=quantity,
        weight_kg=unit_weight * quantity, closed_at=when, shift=shift, comment=comment, closed_by=employee,
    )
    work.remaining_quantity -= quantity
    if work.remaining_quantity == 0:
        work.status = WorkInProcess.Status.CLOSED
    work.save(update_fields=["remaining_quantity", "status", "updated_at"])
    released = work.remaining_quantity
    if released:
        order = ProductionOrder.objects.select_for_update().get(pk=work.order_id)
        order.remaining_quantity += released
        order.status = ProductionOrder.Status.OPEN
        order.save(update_fields=["remaining_quantity", "status", "updated_at"])
        work.remaining_quantity = 0
        work.status = WorkInProcess.Status.CLOSED
        work.save(update_fields=["remaining_quantity", "status", "updated_at"])
        AuditEvent.objects.create(
            user=user, action="RELEASE_PRODUCTION", entity="WorkInProcess", entity_id=work.folio,
            data={"order": order.folio, "released_quantity": str(released),
                  "machine": work.machine.code})
    AuditEvent.objects.create(user=user, action="CLOSE_PRODUCTION", entity="ProductionClose", entity_id=close.folio,
        data={"work_item": work.folio, "quantity": str(quantity), "weight_kg": str(close.weight_kg)})
    return close
