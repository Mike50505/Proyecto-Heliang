import csv
import re
from itertools import islice
from fractions import Fraction
from uuid import uuid4
from io import BytesIO
from zipfile import BadZipFile
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Max, Q, Sum, Value, When
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.datetime import to_excel
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils.exceptions import InvalidFileException
from .access import access_for, module_required
from .forms import (BulkProgramForm, CloseProductionForm, ProcessMovementForm,
                    ProductionOrderEditForm, ProgramOrderForm, StartProductionForm,
                    SurplusMovementForm, UniverseImportForm, UniversePartForm)
from .formatting import (diameter_category, diameter_category_sort_key,
                         format_diameter_fraction)
from .models import (AuditEvent, Client, Inventory, InventoryBucket, Machine, Movement, Part, Process,
                     ProductionClose, ProductionOrder, WorkInProcess, ProgramImportPreview)
from .security import MAX_XLSX_ROWS, spreadsheet_safe, validate_xlsx_archive
from .services import (close_production, create_program_order, move_process_material, move_surplus,
                       delete_production_orders, edit_production_order, resolve_program_client,
                       set_production_order_priority, reorder_production_order_within_diameter, start_production)


@login_required
def dashboard(request):
    context = {
        "open_orders": ProductionOrder.objects.filter(status=ProductionOrder.Status.OPEN).count(),
        "active_work": WorkInProcess.objects.filter(status=WorkInProcess.Status.ACTIVE).count(),
        "closed_count": ProductionClose.objects.count(),
        "part_count": Inventory.objects.count(),
        "recent_closes": ProductionClose.objects.select_related("work_item__order__part", "work_item__machine")[:8],
    }
    return render(request, "operations/dashboard.html", context)


@login_required
@module_required("program_loading")
def order_list(request):
    orders = ProductionOrder.objects.select_related("part", "part__client")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    start = _valid_date(request.GET.get("start"))
    end = _valid_date(request.GET.get("end"))
    priority_only = request.GET.get("priority") == "1"
    if query:
        orders = orders.filter(
            Q(folio__icontains=query) | Q(program__icontains=query) |
            Q(part__number__icontains=query) | Q(part__client__name__icontains=query)
        )
    valid_statuses = {value for value, _ in ProductionOrder.Status.choices}
    if status in valid_statuses:
        orders = orders.filter(status=status)
    else:
        status = ""
    if start:
        orders = orders.filter(required_date__gte=start)
    if end:
        orders = orders.filter(required_date__lte=end)
    if priority_only:
        priority_orders = list(orders.filter(priority__isnull=False))
        for order in priority_orders:
            order.diameter_group = diameter_category(order.part.diameter)
        priority_orders.sort(key=lambda order: (
            diameter_category_sort_key(order.diameter_group),
            order.priority, order.required_date or date.max, order.created_at, order.pk,
        ))
        visible_orders = priority_orders[:500]
        diameter_totals = {}
        for order in visible_orders:
            diameter_totals[order.diameter_group] = diameter_totals.get(order.diameter_group, 0) + 1
        previous_group = None
        group_index = -1
        position_in_group = 0
        for order in visible_orders:
            order.starts_diameter_group = order.diameter_group != previous_group
            if order.starts_diameter_group:
                group_index += 1
                position_in_group = 0
            position_in_group += 1
            order.diameter_priority = position_in_group
            order.diameter_tone = group_index % 4
            order.diameter_group_size = diameter_totals[order.diameter_group]
            previous_group = order.diameter_group
    else:
        visible_orders = orders.order_by("-created_at")[:500]
    return render(request, "operations/order_list.html", {
        "orders": visible_orders, "query": query, "status": status,
        "priority_only": priority_only,
        "start": start.isoformat() if start else "", "end": end.isoformat() if end else "",
        "status_choices": ProductionOrder.Status.choices,
    })


def _valid_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@login_required
@module_required("program_loading")
def edit_order(request, pk):
    order = get_object_or_404(ProductionOrder.objects.select_related("part"), pk=pk)
    form = ProductionOrderEditForm(request.POST or None, instance=order)
    if request.method == "POST" and form.is_valid():
        try:
            order = edit_production_order(
                order_id=order.pk, user=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"La orden {order.folio} fue actualizada.")
            return redirect("order-list")
    return render(request, "operations/form.html", {
        "form": form, "title": f"Editar orden {order.folio}", "button": "Guardar cambios",
    })


@login_required
@module_required("program_loading")
def update_order_priority(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "MÃ©todo no permitido."}, status=405)
    order = get_object_or_404(ProductionOrder, pk=pk)
    raw_priority = request.POST.get("priority", "").strip()
    if raw_priority:
        try:
            priority = int(raw_priority)
        except ValueError:
            return JsonResponse({"error": "La prioridad debe ser un entero mayor que cero."}, status=400)
        if priority < 1:
            return JsonResponse({"error": "La prioridad debe ser un entero mayor que cero."}, status=400)
    else:
        priority = None
    scope = request.POST.get("priority_scope", "")
    if scope == "diameter":
        if priority is None:
            return JsonResponse({"error": "Indica una posición dentro del diámetro."}, status=400)
        try:
            scope_ids = [int(value) for value in request.POST.get("scope_ids", "").split(",")]
        except ValueError:
            return JsonResponse({"error": "El grupo de órdenes es inválido."}, status=400)
        try:
            updated = reorder_production_order_within_diameter(
                order=order, position=priority, scope_ids=scope_ids, user=request.user)
        except ValidationError as exc:
            return JsonResponse({"error": exc.messages[0]}, status=409)
        return JsonResponse({"priority": updated.priority, "display": f"{priority:02d}"})
    if scope:
        return JsonResponse({"error": "Tipo de prioridad inválido."}, status=400)
    set_production_order_priority(order=order, priority=priority, user=request.user)
    return JsonResponse({"priority": priority, "display": f"{priority:02d}" if priority else ""})


@login_required
@module_required("program_loading")
def delete_order(request, pk):
    order = get_object_or_404(ProductionOrder, pk=pk)
    has_production = order.work_items.exists()
    has_material = InventoryBucket.objects.filter(
        kind="PROGRAM", name=order.program, quantity__gt=0).exists()
    blocked = has_production or has_material
    if request.method == "POST":
        deleted, blocked_count = delete_production_orders(
            order_ids=[order.pk], user=request.user, source="single")
        if blocked_count:
            messages.error(request, "No se puede eliminar una orden con producción o material asociado.")
            return redirect("order-list")
        messages.success(request, f"La orden {order.folio} fue eliminada.")
        return redirect("order-list")
    return render(request, "operations/order_confirm_delete.html", {
        "order": order, "blocked": blocked,
    })


@login_required
@module_required("program_loading")
def bulk_delete_orders(request):
    if request.method != "POST":
        return redirect("order-list")

    raw_ids = request.POST.getlist("order_ids")
    try:
        selected_ids = list(dict.fromkeys(int(value) for value in raw_ids))
    except (TypeError, ValueError):
        messages.error(request, "La selección contiene una orden inválida.")
        return redirect("order-list")
    if not selected_ids:
        messages.error(request, "Selecciona al menos una fila para eliminar.")
        return redirect("order-list")
    if len(selected_ids) > 500:
        messages.error(request, "Solo se pueden eliminar hasta 500 filas a la vez.")
        return redirect("order-list")

    deleted_count, blocked_count = delete_production_orders(
        order_ids=selected_ids, user=request.user, source="bulk_selection")

    if deleted_count:
        messages.success(request, f"Se eliminaron {deleted_count} órdenes seleccionadas.")
    if blocked_count:
        messages.error(request, (
            f"No se eliminaron {blocked_count} órdenes porque tienen producción "
            "o material asociado."
        ))
    return redirect("order-list")


@login_required
@module_required("program_loading")
def load_program(request):
    form = ProgramOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        employee = request.user
        try:
            order = create_program_order(
                client_name=form.cleaned_data["client"], part_number=form.cleaned_data["part_number"],
                program=form.cleaned_data["program"], quantity=form.cleaned_data["quantity"],
                required_date=form.cleaned_data["required_date"], line=form.cleaned_data["line"],
                priority=form.cleaned_data["priority"],
                comment=form.cleaned_data["comment"], employee=employee, user=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Programa cargado correctamente con el folio {order.folio}.")
            return redirect("order-list")
    return render(request, "operations/program_load.html", {"form": form, "active_tab": "single"})


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _cell_quantity(value):
    # El archivo original tiene cantidades numéricas con formato de fecha.
    # openpyxl las convierte a datetime; el serial recupera el número capturado.
    if isinstance(value, (datetime, date, time)):
        return Decimal(str(to_excel(value)))
    return Decimal(str(value).replace(",", ""))


@login_required
@module_required("program_loading")
def download_program_template(request):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    headers = ["ID Cliente", "Orden de Produccion", "Linea Prod Clte",
               "Fecha de Entrega", "Num. Parte", "Cantidad", "Linea"]
    sheet.append(headers)

    header_fill = PatternFill("solid", fgColor="0875BD")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:G1000"
    widths = {"A": 18, "B": 25, "C": 22, "D": 20, "E": 22, "F": 15, "G": 18}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    for row in range(2, 1001):
        sheet.cell(row, 4).number_format = "dd/mm/yyyy"
        sheet.cell(row, 6).number_format = "0.###"

    positive_quantity = DataValidation(
        type="decimal", operator="greaterThan", formula1="0", allow_blank=True)
    positive_quantity.error = "La cantidad debe ser un número mayor que cero."
    positive_quantity.errorTitle = "Cantidad inválida"
    positive_quantity.prompt = "Captura una cantidad mayor que cero."
    positive_quantity.promptTitle = "Cantidad"
    positive_quantity.showErrorMessage = True
    positive_quantity.showInputMessage = True
    sheet.add_data_validation(positive_quantity)
    positive_quantity.add("F2:F1000")

    instructions = workbook.create_sheet("Instrucciones")
    instructions.column_dimensions["A"].width = 28
    instructions.column_dimensions["B"].width = 85
    instructions.append(["Campo", "Descripción"])
    descriptions = [
        ("ID Cliente", "Identificador o nombre del cliente. Obligatorio."),
        ("Orden de Produccion", "Número del programa u orden del cliente. Obligatorio."),
        ("Linea Prod Clte", "Línea de producción del cliente. Opcional."),
        ("Fecha de Entrega", "Fecha en formato dd/mm/aaaa. Opcional."),
        ("Num. Parte", "Número de parte. Obligatorio."),
        ("Cantidad", "Cantidad numérica mayor que cero. Obligatorio."),
        ("Linea", "Línea interna asignada al programa. Opcional; tiene prioridad sobre Linea Prod Clte."),
    ]
    for description in descriptions:
        instructions.append(description)
    for cell in instructions[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
    instructions.freeze_panes = "A2"

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="plantilla_carga_programas.xlsx"'
    return response


@login_required
@module_required("program_loading")
def download_completed_programs(request):
    orders = ProductionOrder.objects.filter(
        status=ProductionOrder.Status.COMPLETE
    ).select_related("part", "part__client").annotate(
        completed_quantity=Sum("work_items__closes__quantity"),
        last_close=Max("work_items__closes__closed_at"),
    ).order_by("program", "part__client__name", "part__number")[:10000]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Programas completados"
    headers = [
        "Semana / Orden de Produccion", "Folio", "ID Cliente", "Cliente",
        "Num. Parte", "Cantidad Programada", "Cantidad Terminada", "Restante",
        "Fecha de Entrega", "Linea", "Estado", "Ultimo Cierre",
    ]
    sheet.append(headers)
    header_fill = PatternFill("solid", fgColor="0875BD")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")

    for order in orders:
        client = order.part.client
        completed = order.completed_quantity
        if completed is None:
            completed = order.quantity - order.remaining_quantity
        last_close = order.last_close
        if last_close and timezone.is_aware(last_close):
            last_close = timezone.localtime(last_close).replace(tzinfo=None)
        sheet.append([
            spreadsheet_safe(order.program), spreadsheet_safe(order.folio),
            spreadsheet_safe(client.external_id if client else ""),
            spreadsheet_safe(client.name if client else ""),
            spreadsheet_safe(order.part.number), order.quantity,
            completed, order.remaining_quantity, order.required_date, order.line,
            order.get_status_display(), last_close,
        ])

    widths = [30, 22, 16, 26, 22, 21, 20, 14, 18, 18, 16, 22]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:L{max(sheet.max_row, 1)}"
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row, 9).number_format = "dd/mm/yyyy"
        sheet.cell(row, 12).number_format = "dd/mm/yyyy hh:mm"
        for column in (6, 7, 8):
            sheet.cell(row, column).number_format = "0.###"

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = timezone.localdate().strftime("programas_completados_%Y-%m-%d.xlsx")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@module_required("program_loading")
def bulk_load_program(request):
    if request.method == "POST" and request.POST.get("action") == "confirm":
        form = BulkProgramForm(request.POST)
        try:
            added = 0
            with transaction.atomic():
                preview_record = ProgramImportPreview.objects.select_for_update().get(
                    token=request.POST.get("preview_token", ""), user=request.user)
                if preview_record.confirmed_at:
                    messages.info(request, "Esta carga ya fue confirmada. Para una nueva producción, "
                                  "selecciona el archivo y genera otra vista previa.")
                    return redirect("order-list")
                if preview_record.expires_at <= timezone.now():
                    raise ValidationError(
                        "La vista previa venció. Selecciona el archivo nuevamente.")
                payload = preview_record.payload
                checked_rows = [row["row_number"] for row in payload["rows"]
                                if request.POST.get(f"priority_check_{row['row_number']}") in {"1", "on", "true"}]
                pending_rows = []
                for row in payload["rows"]:
                    raw_priority = request.POST.get(f"priority_{row['row_number']}", "").strip()
                    try:
                        priority = (int(raw_priority) if raw_priority else
                                    checked_rows.index(row["row_number"]) + 1
                                    if row["row_number"] in checked_rows else None)
                    except (TypeError, ValueError):
                        raise ValidationError(f"La prioridad de la fila {row['row_number']} debe ser un entero mayor que cero.")
                    if priority is not None and priority < 1:
                        raise ValidationError(f"La prioridad de la fila {row['row_number']} debe ser un entero mayor que cero.")
                    pending_rows.append((priority, row))
                # Insert in priority order: each creation renumbers the queue.
                # Processing Excel order would let later inserts overtake earlier clicks.
                pending_rows.sort(key=lambda item: (item[0] is None, item[0] or 0))
                for priority, row in pending_rows:
                    client = resolve_program_client(client_reference=row["reference"],
                                                    part_number=row["part_number"])
                    if client.pk != row["client_id"]:
                        raise ValidationError("Cambió el cliente de una fila. Genera otra vista previa.")
                    create_program_order(
                        client_name=row["reference"], client=client,
                        program=row["program"], part_number=row["part_number"],
                        quantity=Decimal(row["quantity"]), line=row["line"],
                        required_date=date.fromisoformat(row["required_date"]) if row["required_date"] else None,
                        priority=priority,
                        employee=request.user, user=request.user,
                        comment=f"Carga masiva: {payload['filename']}")
                    added += 1
                AuditEvent.objects.create(user=request.user, action="BULK_IMPORT_RESULT",
                    entity="ProductionOrder", data={"file": payload["filename"],
                        "added": added, "skipped": 0, "batch_id": payload["batch_id"]})
                preview_record.confirmed_at = timezone.now()
                preview_record.save(update_fields=["confirmed_at"])
        except (ProgramImportPreview.DoesNotExist, ValueError):
            form.add_error(None, "La vista previa venció o no es válida. Selecciona el archivo nuevamente.")
        except (ValidationError, KeyError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Carga masiva terminada: {added} órdenes nuevas agregadas.")
            return redirect("order-list")
        return render(request, "operations/program_load.html", {"form": form, "active_tab": "bulk"})
    form = BulkProgramForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            validate_xlsx_archive(form.cleaned_data["file"])
            workbook = load_workbook(form.cleaned_data["file"], data_only=True, read_only=True)
            sheet = workbook["Sheet1"] if "Sheet1" in workbook.sheetnames else workbook.active
            expected = ["ID Cliente", "Orden de Produccion", "Linea Prod Clte",
                        "Fecha de Entrega", "Num. Parte", "Cantidad"]
            actual = [_cell_text(sheet.cell(1, col).value) for col in range(1, 7)]
            line_header = _cell_text(sheet.cell(1, 7).value)
            if actual != expected or line_header not in ("", "Linea"):
                raise ValidationError(
                    "Los encabezados no coinciden con la plantilla. Se esperan: "
                    + ", ".join(expected + ["Linea"]))
            rows, errors = [], []
            for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                if row_number > MAX_XLSX_ROWS + 1:
                    raise ValidationError(
                        f"El archivo excede el máximo de {MAX_XLSX_ROWS} filas de datos.")
                client, program, customer_line = map(_cell_text, row[:3])
                required, part_number, raw_quantity = row[3], _cell_text(row[4]), row[5]
                line = _cell_text(row[6] if len(row) > 6 else "") or customer_line
                if not any((client, program, part_number, raw_quantity)):
                    continue
                try:
                    quantity = _cell_quantity(raw_quantity)
                except (InvalidOperation, TypeError, ValueError):
                    errors.append(f"Fila {row_number}: cantidad inválida.")
                    continue
                if not client or not program or not part_number or quantity <= 0:
                    errors.append(f"Fila {row_number}: cliente, orden, parte y cantidad son obligatorios.")
                    continue
                if isinstance(required, datetime):
                    required = required.date()
                elif not isinstance(required, date):
                    required = None
                rows.append((row_number, client, program, line, required, part_number, quantity))
            workbook.close()
            preview, payload_rows = [], []
            added = 0
            for row_number, client, program, line, required, part_number, quantity in rows:
                item = {"row_number": row_number, "reference": client, "program": program,
                        "line": line, "required_date": required.isoformat() if required else "",
                        "part_number": part_number, "quantity": str(quantity), "priority": ""}
                try:
                    resolved_client = resolve_program_client(client_reference=client, part_number=part_number)
                    item["client_id"] = resolved_client.pk
                    item["client_name"] = resolved_client.name
                    item["status"] = "Agregar como orden nueva"
                    added += 1
                    payload_rows.append(item.copy())
                except ValidationError as exc:
                    item["status"] = "Error: " + "; ".join(exc.messages)
                    errors.append(f"Fila {row_number}: " + "; ".join(exc.messages))
                preview.append(item)
            if errors:
                form.add_error("file", ValidationError(errors))
            if not rows:
                form.add_error("file", "El archivo no contiene filas válidas para importar.")
            token = ""
            if rows and not errors:
                token = str(uuid4())
                ProgramImportPreview.objects.create(
                    token=token, user=request.user,
                    payload={"rows": payload_rows, "batch_id": str(uuid4()),
                             "filename": request.FILES["file"].name},
                    expires_at=timezone.now() + timedelta(minutes=30),
                )
            return render(request, "operations/program_load.html", {
                "form": form, "active_tab": "bulk", "preview": preview,
                "preview_token": token, "preview_added": added,
                "preview_skipped": len(payload_rows) - added, "preview_errors": len(errors),
            })
        except (ValidationError, KeyError, ValueError, BadZipFile, InvalidFileException) as exc:
            form.add_error("file", exc)
    return render(request, "operations/program_load.html", {"form": form, "active_tab": "bulk"})


@login_required
@module_required("surplus")
def surplus(request):
    form = SurplusMovementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        employee = request.user
        try:
            move_surplus(part=form.cleaned_data["part"], action=form.cleaned_data["action"],
                         quantity=form.cleaned_data["quantity"], employee=employee,
                         program=form.cleaned_data["program"], comment=form.cleaned_data["comment"],
                         user=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Movimiento de material sobrante registrado.")
            return redirect("inventory-list")
    recent = Movement.objects.filter(movement_type=Movement.Type.SURPLUS).select_related("part", "employee").order_by("-occurred_at")[:12]
    return render(request, "operations/surplus.html", {"form": form, "recent": recent})


@login_required
@module_required("process_material")
def process_list(request):
    processes = Process.objects.filter(active=True).prefetch_related("machine_set")
    return render(request, "operations/process_list.html", {"processes": processes})


@login_required
@module_required("universe")
def universe(request):
    edit_part = get_object_or_404(Part, pk=request.POST.get("part_id")) if request.method == "POST" and request.POST.get("action") == "edit" else None
    part_form = UniversePartForm(request.POST or None, instance=edit_part)
    import_form = UniverseImportForm(request.POST or None, request.FILES or None)
    access = access_for(request.user)
    if request.method == "POST" and request.POST.get("action") in {"add", "edit"} and not access.universe_edit:
        messages.error(request, "No tienes permiso para editar el Universo.")
        return redirect("universe")
    if request.method == "POST" and request.POST.get("action") == "import" and not access.universe_import:
        messages.error(request, "No tienes permiso para importar el Universo.")
        return redirect("universe")
    if request.method == "POST" and request.POST.get("action") == "add" and part_form.is_valid():
        part = part_form.save(commit=False)
        part.in_universe_ramos = True
        part.save()
        messages.success(request, "La pieza se agregÃ³ al Universo Ramos Arizpe.")
        return redirect("universe")
    if request.method == "POST" and request.POST.get("action") == "edit" and part_form.is_valid():
        part = part_form.save(commit=False)
        part.in_universe_ramos = True
        part.save()
        messages.success(request, "Pieza actualizada correctamente.")
        return redirect("universe")
    if request.method == "POST" and request.POST.get("action") == "import" and import_form.is_valid():
        try:
            created, updated, skipped = _import_universe_workbook(import_form.cleaned_data["file"])
        except (ValidationError, BadZipFile, InvalidFileException, KeyError) as exc:
            import_form.add_error("file", exc)
        else:
            messages.success(request, f"Universo actualizado: {created} piezas nuevas, {updated} actualizadas y {skipped} filas omitidas.")
            return redirect("universe")
    query = request.GET.get("q", "").strip()
    diameter_filter = request.GET.get("diameter", "").strip()
    client_filter = request.GET.get("client", "").strip()
    parts = Part.objects.filter(in_universe_ramos=True).select_related("client").order_by("number")
    if query:
        parts = parts.filter(Q(number__icontains=query) | Q(diameter__icontains=query) |
                             Q(client__name__icontains=query))
    if diameter_filter:
        parts = parts.filter(diameter__icontains=diameter_filter)
    if client_filter:
        parts = parts.filter(client__name__icontains=client_filter)
    all_parts = Part.objects.filter(in_universe_ramos=True).select_related("client")
    diameters = sorted({diameter_category(part.diameter) for part in all_parts if part.diameter}, key=diameter_category_sort_key)
    clients = sorted({part.client.name for part in all_parts if part.client}, key=str.casefold)
    return render(request, "operations/universe.html", {
        "part_form": part_form, "import_form": import_form, "parts": parts[:1000], "query": query,
        "diameter_filter": diameter_filter, "client_filter": client_filter,
        "diameters": diameters, "clients": clients,
        "universe_total": all_parts.count(), "universe_diameter_count": len(diameters),
        "universe_client_count": len(clients),
    })


def _universe_text(value):
    return "" if value is None else str(value).strip()


def _universe_key(value):
    return re.sub(r"[^a-z0-9]", "", _universe_text(value).lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")).replace("ñ", "n")


@transaction.atomic
def _import_universe_workbook(upload):
    validate_xlsx_archive(upload)
    workbook = load_workbook(upload, data_only=True, read_only=True)
    sheet = workbook["Sheet1 (2)"] if "Sheet1 (2)" in workbook.sheetnames else workbook.active
    header_row = None
    columns = {}
    for index, values in enumerate(sheet.iter_rows(min_row=1, max_row=10, values_only=True), 1):
        keys = {}
        for position, value in enumerate(values):
            key = _universe_key(value)
            if key: keys.setdefault(key, position)
        if any("numerodeparte" in key or "numpart" in key for key in keys):
            header_row, columns = index, keys
            break
    if header_row is None:
        workbook.close()
        raise ValidationError("No se encontrÃ³ una columna de nÃºmero de parte en el Excel.")
    def col(*names):
        for name in names:
            if name in columns:
                return columns[name]
        return None
    part_col = col("numerodeparte", "numpart", "partnumber")
    diameter_col = col("diametro", "diameter")
    client_col = col("cliente", "customer")
    external_col = col("id", "idcliente", "clienteid")
    if part_col is None or client_col is None or diameter_col is None:
        workbook.close()
        raise ValidationError("El Excel debe contener CLIENTE, NÚMERO DE PARTE y DIAMETRO.")
    data_rows = list(islice(sheet.iter_rows(min_row=header_row + 1, values_only=True), MAX_XLSX_ROWS + 1))
    if len(data_rows) > MAX_XLSX_ROWS:
        workbook.close()
        raise ValidationError(f"El archivo excede el máximo de {MAX_XLSX_ROWS} filas de datos.")
    diameter_values = {}
    for values in data_rows:
        number = _universe_text(values[part_col] if len(values) > part_col else "")
        diameter = _universe_text(values[diameter_col] if len(values) > diameter_col else "")
        if number and diameter:
            diameter_values.setdefault(number, set()).add(diameter)
    def diameter_key(value):
        try:
            return Fraction(value.replace(",", "."))
        except (ValueError, ZeroDivisionError):
            return value.casefold()
    conflicting_parts = {
        number for number, values in diameter_values.items()
        if len({diameter_key(value) for value in values}) > 1
    }
    preferred_diameters = {
        number: max(values, key=lambda value: ("/" in value, len(value), value))
        for number, values in diameter_values.items() if number not in conflicting_parts
    }
    source_numbers = {
        _universe_text(values[part_col]) for values in data_rows
        if len(values) > part_col and _universe_text(values[part_col])
        and _universe_key(values[part_col]) != "numerodeparte"
    }
    if not source_numbers:
        workbook.close()
        raise ValidationError("El Excel no contiene números de parte.")
    Part.objects.filter(in_universe_ramos=True).exclude(number__in=source_numbers).update(in_universe_ramos=False)
    created = updated = skipped = 0
    for values in data_rows:
        part_number = _universe_text(values[part_col] if part_col is not None and len(values) > part_col else "")
        if not part_number or _universe_key(part_number) == "numerodeparte":
            skipped += 1
            continue
        client_name = _universe_text(values[client_col] if client_col is not None and len(values) > client_col else "")
        external_id = _universe_text(values[external_col] if external_col is not None and len(values) > external_col else "")
        if external_id.upper() in {"#N/A", "N/A", "NA"}: external_id = ""
        client = None
        if client_name:
            code = re.sub(r"[^A-Z0-9]+", "-", client_name.upper()).strip("-")[:30] or "SIN-CLIENTE"
            client, _ = Client.objects.get_or_create(code=code, defaults={"name": client_name, "external_id": external_id})
            changes = []
            if client.name != client_name: client.name = client_name; changes.append("name")
            if external_id and client.external_id != external_id: client.external_id = external_id; changes.append("external_id")
            if changes: client.save(update_fields=[*changes, "updated_at"])
        part, was_created = Part.objects.get_or_create(
            number=part_number, defaults={"client": client, "in_universe_ramos": True})
        changes = []
        if not part.in_universe_ramos:
            part.in_universe_ramos = True
            changes.append("in_universe_ramos")
        diameter = preferred_diameters.get(part_number, "")
        if client and part.client_id != client.pk: part.client = client; changes.append("client")
        if diameter and part.diameter != diameter:
            part.diameter = diameter
            changes.append("diameter")
        if changes: part.save(update_fields=[*changes, "updated_at"])
        created += int(was_created); updated += int(not was_created and bool(changes))
    workbook.close()
    return created, updated, skipped


@login_required
@module_required("process_material")
def process_material(request):
    form = ProcessMovementForm(request.POST or None)
    selected_part = None
    if request.method == "POST" and request.POST.get("part"):
        selected_part = form.fields["part"].queryset.filter(pk=request.POST["part"]).first()
    if request.method == "POST" and form.is_valid():
        selected_part = form.cleaned_data["part"]
        employee = request.user
        try:
            move_process_material(
                part=selected_part, source_process=form.cleaned_data["source_process"],
                destination_process=form.cleaned_data["destination_process"],
                program=form.cleaned_data["program"], quantity=form.cleaned_data["quantity"],
                employee=employee, comment=form.cleaned_data["comment"], user=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "El material fue transferido al siguiente proceso.")
            return redirect(f"{request.path}?part={selected_part.pk}")
    part_id = request.GET.get("part")
    if part_id and not selected_part:
        selected_part = form.fields["part"].queryset.filter(pk=part_id).first()
    inventory = None
    buckets = []
    programs = []
    process_total = 0
    if selected_part:
        inventory = Inventory.objects.filter(part=selected_part).first()
        if inventory:
            buckets = inventory.buckets.filter(kind="PROCESS").order_by("name")
            programs = inventory.buckets.filter(kind="PROGRAM", quantity__gt=0).order_by("name")
            process_total = buckets.aggregate(total=Sum("quantity"))["total"] or 0
    recent = Movement.objects.filter(movement_type=Movement.Type.INVENTORY).select_related(
        "part", "employee").order_by("-occurred_at")[:15]
    return render(request, "operations/process_material.html", {
        "form": form, "selected_part": selected_part, "inventory": inventory,
        "buckets": buckets, "programs": programs, "process_total": process_total,
        "recent": recent})


@login_required
@module_required("heliang")
def work_list(request):
    items = WorkInProcess.objects.select_related("order__part", "machine").order_by("-started_at")[:500]
    return render(request, "operations/work_list.html", {"items": items})


@login_required
@module_required("heliang")
def heliang(request):
    action = request.POST.get("action")
    selected_order = None
    if request.method == "GET" and request.GET.get("order"):
        selected_order = ProductionOrder.objects.filter(
            pk=request.GET["order"], status=ProductionOrder.Status.OPEN
        ).first()
    start_initial = ({"order": selected_order, "quantity": _quantity_text(selected_order.remaining_quantity)}
                     if selected_order else None)
    start_form = StartProductionForm(
        request.POST if action == "start" else None,
        prefix="start", initial=start_initial,
    )
    selected_work = None
    if request.method == "GET" and request.GET.get("work"):
        selected_work = WorkInProcess.objects.filter(
            pk=request.GET["work"], status=WorkInProcess.Status.ACTIVE
        ).select_related("order__part", "machine").first()
    close_initial = ({"work_item": selected_work, "quantity": _quantity_text(selected_work.remaining_quantity)}
                     if selected_work else None)
    close_form = CloseProductionForm(
        request.POST if action == "close" else None,
        prefix="close", initial=close_initial,
    )
    if request.method == "POST" and action == "start" and start_form.is_valid():
        employee = request.user
        try:
            work = start_production(
                order=start_form.cleaned_data["order"], machine=start_form.cleaned_data["machine"],
                quantity=start_form.cleaned_data["quantity"], employee=employee, user=request.user)
        except ValidationError as exc:
            start_form.add_error(None, exc)
        else:
            messages.success(request, f"Orden {work.order.folio} asignada a {work.machine.code} con folio {work.folio}.")
            return redirect("heliang")
    if request.method == "POST" and action == "close" and close_form.is_valid():
        employee = request.user
        try:
            close = close_production(
                work_item=close_form.cleaned_data["work_item"],
                quantity=close_form.cleaned_data["quantity"], employee=employee,
                user=request.user, comment=close_form.cleaned_data["comment"])
        except ValidationError as exc:
            close_form.add_error(None, exc)
        else:
            messages.success(request, f"Producción cerrada con el folio {close.folio}.")
            return redirect("heliang")
    if False:  # Pausing is handled by the single release button in the close form.
        try:
            work = pause_production(work_item=pause_form.cleaned_data["work_item"],
                                    employee=request.user, user=request.user,
                                    comment=pause_form.cleaned_data["comment"])
        except ValidationError as exc:
            pause_form.add_error(None, exc)
        else:
            messages.success(request, f"Producción {work.folio} pausada; la máquina quedó disponible.")
            return redirect("heliang")
    if False:  # Resuming is handled by returning the unproduced balance to open orders.
        try:
            work = resume_production(work_item=resume_form.cleaned_data["work_item"],
                                     machine=resume_form.cleaned_data["machine"],
                                     employee=request.user, user=request.user)
        except ValidationError as exc:
            resume_form.add_error(None, exc)
        else:
            messages.success(request, f"Producción {work.folio} reanudada en {work.machine.code}.")
            return redirect("heliang")
    open_orders_query = ProductionOrder.objects.filter(status=ProductionOrder.Status.OPEN).select_related(
        "part", "part__client").annotate(
            priority_sort=Case(When(priority__isnull=True, then=Value(2147483647)),
                               default="priority", output_field=IntegerField())
        ).order_by("priority_sort", "required_date", "created_at")
    priority_orders = list(open_orders_query.filter(priority__isnull=False)[:100])
    priority_orders.sort(key=lambda order: (
        diameter_category_sort_key(diameter_category(order.part.diameter)),
        order.priority, order.required_date or date.max, order.created_at,
    ))
    diameter_totals = {}
    for order in priority_orders:
        group = diameter_category(order.part.diameter)
        diameter_totals[group] = diameter_totals.get(group, 0) + 1
    diameter_positions = {}
    previous_group = None
    group_index = -1
    for order in priority_orders:
        order.diameter_group = diameter_category(order.part.diameter)
        order.starts_diameter_group = order.diameter_group != previous_group
        if order.starts_diameter_group:
            group_index += 1
        order.diameter_tone = group_index % 4
        order.diameter_group_size = diameter_totals[order.diameter_group]
        diameter_positions[order.diameter_group] = diameter_positions.get(order.diameter_group, 0) + 1
        order.heliang_priority = diameter_positions[order.diameter_group]
        previous_group = order.diameter_group
    open_orders = list(open_orders_query[:100])
    for order in open_orders:
        order.part.diameter = format_diameter_fraction(order.part.diameter)
    active_items = WorkInProcess.objects.filter(status=WorkInProcess.Status.ACTIVE).select_related(
        "order__part", "machine", "started_by").order_by("started_at")
    recent_closes = ProductionClose.objects.select_related(
        "work_item__order__part", "work_item__machine", "closed_by").order_by("-closed_at")[:30]
    occupied_ids = set(active_items.values_list("machine_id", flat=True))
    machines = Machine.objects.filter(active=True).select_related("process").order_by("code")
    machine_rows = [{"machine": machine, "occupied": machine.pk in occupied_ids}
                    for machine in machines]
    return render(request, "operations/heliang.html", {
        "start_form": start_form, "close_form": close_form, "open_orders": open_orders,
        "priority_orders": priority_orders,
        "priority_keys": list(ProductionOrder.objects.filter(priority__isnull=False).values_list("program", "part__number")),
        "order_balances": {str(order.pk): str(order.remaining_quantity) for order in open_orders},
        "active_items": active_items, "recent_closes": recent_closes,
        "machine_rows": machine_rows, "selected_order": selected_order,
        "selected_work": selected_work})


def _quantity_text(value):
    return format(value, "f").rstrip("0").rstrip(".")


@login_required
@module_required("line_dashboard")
def line_dashboard(request):
    return render(request, "operations/line_dashboard.html", _line_dashboard_context())


def _line_dashboard_context():
    now = timezone.localtime()
    today = now.date()
    active_items = list(WorkInProcess.objects.filter(
        status=WorkInProcess.Status.ACTIVE).select_related(
        "order__part", "order__part__client", "machine", "started_by"))
    active_by_machine = {item.machine_id: item for item in active_items}
    machine_rows = []
    for machine in Machine.objects.filter(active=True).order_by("code"):
        work = active_by_machine.get(machine.pk)
        progress = 0
        if work and work.initial_quantity:
            progress = min(100, round(float(
                (work.initial_quantity - work.remaining_quantity) / work.initial_quantity * 100)))
        machine_rows.append({"machine": machine, "work": work, "progress": progress})
    today_closes = ProductionClose.objects.filter(closed_at__date=today)
    today_summary = today_closes.aggregate(quantity=Sum("quantity"), weight=Sum("weight_kg"))
    process_totals = InventoryBucket.objects.filter(kind="PROCESS", quantity__gt=0).values(
        "name").annotate(total=Sum("quantity")).order_by("-total")[:10]
    open_orders = ProductionOrder.objects.filter(status=ProductionOrder.Status.OPEN).select_related(
        "part", "part__client").order_by("required_date", "created_at")[:8]
    recent_closes = ProductionClose.objects.filter(closed_at__date=today).select_related(
        "work_item__order__part", "work_item__machine").order_by("-closed_at")[:8]
    total_machines = len(machine_rows)
    first_day = today - timedelta(days=6)
    daily_values = {
        row["day"]: row["total"] or 0
        for row in ProductionClose.objects.filter(closed_at__date__gte=first_day)
        .annotate(day=TruncDate("closed_at", tzinfo=timezone.get_current_timezone()))
        .values("day").annotate(total=Sum("quantity"))
    }
    day_names = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
    daily_production = [
        {"label": day_names[(first_day + timedelta(days=index)).weekday()],
         "date": first_day + timedelta(days=index),
         "total": daily_values.get(first_day + timedelta(days=index), 0)}
        for index in range(7)
    ]
    daily_max = max((row["total"] for row in daily_production), default=0) or 1
    for row in daily_production:
        row["height"] = round(float(row["total"] / daily_max * 100))
    machine_output = list(today_closes.values(
        "work_item__machine__code").annotate(total=Sum("quantity")).order_by("-total")[:8])
    machine_max = max((row["total"] for row in machine_output), default=0) or 1
    for row in machine_output:
        row["percent"] = round(float(row["total"] / machine_max * 100))
    utilization = round(len(active_items) / total_machines * 100) if total_machines else 0
    order_counts = dict(ProductionOrder.objects.values_list("status").annotate(total=Count("id")))
    order_total = sum(order_counts.values()) or 1
    order_distribution = [
        {"label": "Abiertas", "value": order_counts.get(ProductionOrder.Status.OPEN, 0), "class": "open",
         "percent": round(order_counts.get(ProductionOrder.Status.OPEN, 0) / order_total * 100)},
        {"label": "Completadas", "value": order_counts.get(ProductionOrder.Status.COMPLETE, 0), "class": "complete",
         "percent": round(order_counts.get(ProductionOrder.Status.COMPLETE, 0) / order_total * 100)},
        {"label": "Canceladas", "value": order_counts.get(ProductionOrder.Status.CANCELLED, 0), "class": "cancelled",
         "percent": round(order_counts.get(ProductionOrder.Status.CANCELLED, 0) / order_total * 100)},
    ]
    return {
        "now": now, "machine_rows": machine_rows, "active_count": len(active_items),
        "available_count": total_machines - len(active_items), "total_machines": total_machines,
        "open_count": ProductionOrder.objects.filter(status=ProductionOrder.Status.OPEN).count(),
        "today_closes_count": today_closes.count(),
        "today_quantity": today_summary["quantity"] or 0,
        "today_weight": today_summary["weight"] or 0,
        "process_totals": process_totals, "open_orders": open_orders,
        "recent_closes": recent_closes,
        "daily_production": daily_production, "machine_output": machine_output,
        "utilization": utilization, "utilization_degrees": utilization * 3.6,
        "order_distribution": order_distribution,
    }


@login_required
@module_required("line_dashboard")
def line_dashboard_data(request):
    context = _line_dashboard_context()
    return JsonResponse({
        "html": render_to_string("operations/line_dashboard.html", context, request=request),
        "updated_at": context["now"].isoformat(),
    })


@login_required
@module_required("line_dashboard")
def progress_dashboard(request):
    return render(request, "operations/progress_dashboard.html", {
        "progress_data": _progress_dashboard_data(),
    })


def _progress_dashboard_data():
    orders = ProductionOrder.objects.exclude(
        status=ProductionOrder.Status.CANCELLED
    ).select_related("part", "part__client").annotate(
        completed_quantity=Sum("work_items__closes__quantity")
    ).order_by("program", "part__client__name", "part__number")[:5000]

    progress_data = []
    for order in orders:
        completed = order.completed_quantity or Decimal("0")
        progress_data.append({
            "folio": order.folio,
            "week": order.program or "Sin semana",
            "client": order.part.client.name if order.part.client else "Sin cliente",
            "part": order.part.number,
            "programmed": float(order.quantity),
            "completed": float(completed),
        })
    return progress_data


@login_required
@module_required("line_dashboard")
def progress_dashboard_data(request):
    return JsonResponse({
        "progress_data": _progress_dashboard_data(),
        "updated_at": timezone.now().isoformat(),
    })


@login_required
@module_required("heliang")
def start_work(request):
    form = StartProductionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        employee = request.user
        try:
            work = start_production(order=form.cleaned_data["order"], machine=form.cleaned_data["machine"],
                quantity=form.cleaned_data["quantity"], employee=employee, user=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"La orden pasó a producción con el folio {work.folio}.")
            return redirect("work-list")
    return render(request, "operations/form.html", {"form": form, "title": "Enviar a producción", "button": "Iniciar producción"})


@login_required
@module_required("heliang")
def close_work(request):
    form = CloseProductionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        employee = request.user
        try:
            close = close_production(work_item=form.cleaned_data["work_item"], quantity=form.cleaned_data["quantity"],
                employee=employee, user=request.user, comment=form.cleaned_data["comment"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Producción registrada con el folio {close.folio}.")
            return redirect("report")
    return render(request, "operations/form.html", {"form": form, "title": "Cerrar producción", "button": "Registrar cierre"})


@login_required
@module_required("inventory")
def inventory_list(request):
    query = request.GET.get("q", "").strip()
    rows = Inventory.objects.select_related("part", "part__client").prefetch_related("buckets")
    if query: rows = rows.filter(part__number__icontains=query)
    return render(request, "operations/inventory_list.html", {"rows": rows[:300], "query": query})


@login_required
@module_required("reports")
def report(request):
    rows, filters = _filtered_report_rows(request)
    machines = Machine.objects.filter(work_items__closes__isnull=False).distinct().order_by("code")
    shifts = ProductionClose.objects.exclude(shift="").values_list("shift", flat=True).distinct().order_by("shift")
    return render(request, "operations/report.html", {
        "rows": rows[:1000], "machines": machines, "shifts": shifts,
        "query_string": request.GET.urlencode(), **filters,
    })


def _filtered_report_rows(request):
    rows = ProductionClose.objects.select_related(
        "work_item__order__part", "work_item__machine", "closed_by")
    query = request.GET.get("q", "").strip()
    machine = request.GET.get("machine", "").strip()
    shift = request.GET.get("shift", "").strip()
    start = _valid_date(request.GET.get("start"))
    end = _valid_date(request.GET.get("end"))
    if query:
        rows = rows.filter(
            Q(folio__icontains=query) | Q(work_item__order__folio__icontains=query) |
            Q(work_item__order__program__icontains=query) |
            Q(work_item__order__part__number__icontains=query) |
            Q(work_item__machine__code__icontains=query) |
            Q(closed_by__username__icontains=query) | Q(closed_by__first_name__icontains=query) |
            Q(closed_by__last_name__icontains=query)
        )
    if machine:
        rows = rows.filter(work_item__machine__code=machine)
    if shift:
        rows = rows.filter(shift=shift)
    if start:
        rows = rows.filter(closed_at__date__gte=start)
    if end:
        rows = rows.filter(closed_at__date__lte=end)
    return rows.order_by("-closed_at"), {
        "query": query, "machine": machine, "shift": shift,
        "start": start.isoformat() if start else "", "end": end.isoformat() if end else "",
    }


@login_required
@module_required("reports")
def report_csv(request):
    rows, _ = _filtered_report_rows(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="reporte_produccion.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Folio", "Orden", "Programa", "Número de parte", "Cantidad", "Máquina", "Cierre", "Turno", "Kilogramos", "Operador", "Comentario"])
    for row in rows[:10000]:
        writer.writerow([spreadsheet_safe(row.folio), spreadsheet_safe(row.work_item.order.folio),
            spreadsheet_safe(row.work_item.order.program), spreadsheet_safe(row.work_item.order.part.number),
            row.quantity, spreadsheet_safe(row.work_item.machine.code), row.closed_at,
            spreadsheet_safe(row.shift), row.weight_kg,
            spreadsheet_safe(row.closed_by or ""), spreadsheet_safe(row.comment)])
    return response
