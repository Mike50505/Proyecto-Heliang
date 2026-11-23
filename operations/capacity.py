import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, DateTimeField, F, Q, Sum, Value, When
from django.db.models.functions import TruncDate, TruncWeek
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .access import module_required
from .formatting import diameter_category, diameter_category_sort_key
from .models import AuditEvent, CapacitySettings, ProductionClose, ProductionOrder


WEEK = re.compile(r"(?:(\d{4})[ -]?)?(?:SEMANA|SEM|WK|W|S)?\s*0?(\d{1,2})(?:[ /-]+(\d{4}))?", re.I)
SHARED = ("5/16", "1/4")
SHARED_LABEL = "5/16 + 1/4"
OUTPUT_SHIFTS = ("a", "b", "other")


def week_start(program, created):
    match = WEEK.fullmatch(program.strip())
    if not match:
        return None
    prefix, week, suffix = match.groups()
    year = created.isocalendar().year
    years = [int(prefix or suffix)] if prefix or suffix else [year - 1, year, year + 1]
    starts = []
    for candidate in years:
        try:
            starts.append(date.fromisocalendar(candidate, int(week), 1))
        except ValueError:
            pass
    return min(starts, key=lambda day: abs((day - created).days), default=None)


def week_label(start):
    year, number, _ = start.isocalendar()
    return f"Semana {number:02d} · {year}"


def diameter(value):
    label = diameter_category(value)
    return re.sub(r"^(\d+)\s*mm$", r"\1 mm", label, flags=re.I)


@dataclass
class Progress:
    planned: int = 0
    done: int = 0
    pending: int = 0
    available: int = 0

    def add(self, planned, done, available):
        self.planned += planned
        self.done += done
        self.pending += max(0, planned - done)
        self.available += int(available)

    @property
    def percent(self):
        return 100 * self.done / self.planned if self.planned else 0


def capacity_row(name, limit, planned, carry):
    load = planned + carry
    return dict(name=name, limit=limit, planned=planned, carry=carry, load=load,
                over=limit is not None and load > limit,
                margin=None if limit is None else limit - load)


def midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def operational_closes(closes):
    """Assign Turno B closes before 06:00 to the day the shift began."""
    turno_b = Q(shift__iexact="b") | Q(shift__iexact="turno b")
    operational_at = Case(
        When(turno_b, closed_at__time__lt=time(6), then=F("closed_at") - timedelta(days=1)),
        default=F("closed_at"),
        output_field=DateTimeField(),
    )
    return closes.annotate(operational_at=operational_at).annotate(
        work_date=TruncDate("operational_at", tzinfo=timezone.get_current_timezone())
    )


def output_shift(label):
    name = " ".join(label.casefold().split()).removeprefix("turno ")
    return name if name in ("a", "b") else "other"


def weekly_series(dates, today, workdays, daily_output, target, daily=False):
    totals = Counter()
    rows = []
    for index, day in enumerate(dates, start=1):
        output = Counter({shift: daily_output[day, shift] for shift in OUTPUT_SHIFTS})
        totals.update(output)
        expected = (Decimal(target) / workdays if index <= workdays else Decimal(0)) if daily and target is not None else (
            Decimal(target) * min(index, workdays) / workdays if target is not None else None
        )
        values = output if daily else totals
        actual = values.total() if day <= today else None
        quantities = [values[shift] if day <= today else None for shift in OUTPUT_SHIFTS]
        rows.append((day, actual, expected, *quantities))
    return rows


def configured_machine_code(code, config):
    pieces = code.split()
    return pieces[0] if pieces and pieces[0] in config.machines else code


def physical_output(closes):
    """Group operational-day production by original order and recorded shift."""
    order_path = "work_item__order__"
    fields = ("folio", "program", "part__number", "part__client_id", "part__client__name", "part__diameter")
    return closes.values_list(
        "work_date", *(order_path + field for field in fields), "shift"
    ).annotate(qty=Sum("quantity")).order_by("-work_date", order_path + "folio", "shift")


@login_required
@module_required("line_dashboard")
@never_cache
def dashboard(request):
    config = CapacitySettings.objects.get(pk=1)
    snapshot_at = timezone.now()
    today = timezone.localdate(snapshot_at)
    current = today - timedelta(days=today.weekday())
    physical = request.GET.get("week_mode") == "physical"
    orders = ProductionOrder.objects.exclude(status=ProductionOrder.Status.CANCELLED)
    periods = {current.isoformat(): (current, week_label(current))}
    # A legacy program may contain only S35. Anchor its year to the load date.
    program_dates = orders.annotate(loaded=TruncDate("created_at")).values_list(
        "program", "loaded", "part__client_id", "part__client__name").distinct()
    clients_by_period = defaultdict(dict)
    for program, loaded, cid, customer in program_dates:
        start = week_start(program, loaded)
        key = start.isoformat() if start else "program:" + program
        clients_by_period[key][str(cid or "none")] = customer or "Sin cliente"
        periods[key] = (start, week_label(start) if start else program or "Sin programa")
    if physical:
        periods = {key: value for key, value in periods.items() if value[0]}
        closed_weeks = operational_closes(ProductionClose.objects.filter(closed_at__lt=snapshot_at)).annotate(
            close_week=TruncWeek("operational_at", tzinfo=timezone.get_current_timezone())
        ).order_by().values_list("close_week", flat=True).distinct()
        for week in closed_weeks:
            monday = timezone.localdate(week)
            periods[monday.isoformat()] = (monday, week_label(monday))
    selected = request.GET.get("week", current.isoformat())
    if selected not in periods:
        selected = current.isoformat()
    start, label = periods[selected]
    end = midnight(start + timedelta(days=7)) + timedelta(hours=6) if start else None
    cutoff = min(snapshot_at, end) if end else snapshot_at
    runs = operational_closes(ProductionClose.objects.filter(closed_at__lt=cutoff)).filter(
        work_date__gte=start, work_date__lt=start + timedelta(days=7)
    ) if start else ProductionClose.objects.none()
    actual_by_diameter = defaultdict(Counter)
    physical_load = Counter()
    produced_by_customer = Counter()
    closed_details = []
    close_date = "work_items__closes__closed_at"
    sums = {"done": Sum("work_items__closes__quantity", filter=Q(**{close_date + "__lt": cutoff}))}
    if start:
        sums["prior"] = Sum("work_items__closes__quantity", filter=Q(**{close_date + "__lt": min(midnight(start), cutoff)}))
    records = orders.annotate(loaded=TruncDate("created_at")).values(
        "id", "program", "loaded", "quantity", "status", "remaining_quantity", "folio",
        "part__number", "part__client_id", "part__client__name", "part__diameter"
    ).annotate(**sums).order_by("part__client__name", "part__number", "id")
    client = request.GET.get("client", "")
    clients = clients_by_period[selected]
    if physical:
        # Include customers who closed an older order during this week.
        physical_clients = runs.order_by().values_list(
            "work_item__order__part__client_id", "work_item__order__part__client__name"
        ).distinct()
        for cid, name in physical_clients:
            clients[str(cid or "none")] = name or "Sin cliente"
    if client not in clients:
        client = ""
    details = []
    available_orders = []
    selected_parts = {}
    by_customer, by_diameter = defaultdict(Progress), defaultdict(Progress)
    planned, carry = defaultdict(int), defaultdict(int)
    total = Progress()
    for row in records.iterator():
        order_start = week_start(row["program"], row["loaded"])
        key = order_start.isoformat() if order_start else "program:" + row["program"]
        size = diameter(row["part__diameter"])
        qty = row["quantity"]
        if key != selected:
            if start and order_start and order_start < start:
                carry[size] += max(0, qty - (row["prior"] or 0))
            continue
        done = row["done"] or 0
        planned[size] += qty
        cid = str(row["part__client_id"] or "none")
        name = row["part__client__name"] or "Sin cliente"
        clients[cid] = name
        if client and cid != client:
            continue
        available = row["status"] == ProductionOrder.Status.OPEN and row["remaining_quantity"] > 0
        if available:
            available_orders.append((row["folio"], row["part__number"], name, row["remaining_quantity"]))
        if start:
            selected_parts[row["id"]] = size
        for group in (total, by_customer[cid], by_diameter[size]):
            group.add(qty, done, available)
        details.append((row["folio"], row["part__number"], name, size, qty, done, max(0, qty - done)))
    if physical:
        for work_date, folio, program, part, cid, name, size, shift_label, quantity in physical_output(runs):
            size = diameter(size)
            physical_load[size] += quantity
            cid = str(cid or "none")
            if client and cid != client:
                continue
            produced_by_customer[cid] += quantity
            actual_by_diameter[size][work_date, output_shift(shift_label)] += quantity
            closed_details.append((work_date, folio, program, part, name or "Sin cliente", size, shift_label, quantity))
        total.done = produced_by_customer.total()
        # The customer bar in physical mode shows share of selected production.
        by_customer = {cid: Progress(planned=total.done, done=qty) for cid, qty in produced_by_customer.items()}
        planned, carry = physical_load, Counter()
    sizes = list(config.diameters) + sorted((planned.keys() | carry.keys()) - config.diameters.keys())
    rows = [capacity_row(s, config.diameters[s], planned[s], carry[s]) for s in sizes
            if s in config.diameters and config.diameters[s] is not None and config.diameters[s] > 0]
    weekly_hours = config.hours * config.shifts * config.days
    machine_limits = {code: weekly_hours * machine["rate"] if machine["enabled"] else 0
                      for code, machine in config.machines.items()}
    installed = sum(machine_limits.values())
    plant_limit = min(installed, config.plant_ceiling) if config.plant_ceiling is not None else installed
    plant = capacity_row("Planta", plant_limit, sum(planned.values()), sum(carry.values()))
    pool = capacity_row("5/16 + 1/4", config.shared_limit, sum(planned[s] for s in SHARED), sum(carry[s] for s in SHARED))
    machine_rows = []
    machine_series = []
    diameter_series = []
    machine_daily = defaultdict(Counter)
    machine_options = sorted(code for code, limit in machine_limits.items() if limit > 0)
    diameter_options = sorted((size for size, limit in config.diameters.items() if limit and limit > 0),
                              key=diameter_category_sort_key)
    if config.shared_limit is not None and config.shared_limit > 0:
        diameter_options.append(SHARED_LABEL)
    machine_code = request.GET.get("chart_machine", "")
    chart_diameter = request.GET.get("chart_diameter", "")
    if chart_diameter not in diameter_options:
        chart_diameter = ""
    selected_sizes = SHARED if chart_diameter == SHARED_LABEL else (chart_diameter,) if chart_diameter else ()
    diameter_limit = plant_limit
    if chart_diameter == SHARED_LABEL:
        diameter_limit = config.shared_limit
    elif chart_diameter:
        diameter_limit = config.diameters[chart_diameter]
    day = request.GET.get("day", "")
    shift = request.GET.get("shift", "")
    shift_options = []
    if start:
        dates = [start + timedelta(days=i) for i in range(7)]
        chosen_day = next((d for d in dates if d.isoformat() == day), None)
        for code, work_date, shift_label, quantity in runs.values_list(
            "work_item__machine__code", "work_date", "shift"
        ).annotate(qty=Sum("quantity")):
            machine_daily[configured_machine_code(code, config)][work_date, output_shift(shift_label)] += quantity
        machine_options = sorted(code for code, limit in machine_limits.items() if limit > 0)
        if machine_code not in machine_options:
            machine_code = ""
        if machine_code:
            machine_target = machine_limits.get(machine_code)
            machine_output = machine_daily[machine_code]
        else:
            machine_target = installed
            machine_output = Counter()
            for daily_output in machine_daily.values():
                machine_output.update(daily_output)
        machine_series = weekly_series(dates, today, config.days, machine_output, machine_target, daily=True)

        if physical:
            diameter_output = Counter()
            for size, output_by_day in actual_by_diameter.items():
                if not selected_sizes or size in selected_sizes:
                    diameter_output.update(output_by_day)
            diameter_series = weekly_series(dates, today, config.days, diameter_output, diameter_limit, daily=True)
        else:
            diameter_target = (sum(by_diameter[size].planned for size in selected_sizes) if selected_sizes
                               else total.planned)
            if diameter_target or diameter_limit:
                matching_orders = [order_id for order_id, size in selected_parts.items()
                                   if not selected_sizes or size in selected_sizes]
                closes_by_shift = ProductionClose.objects.filter(work_item__order_id__in=matching_orders,
                                                                   closed_at__lt=cutoff)
                closes_by_shift = operational_closes(closes_by_shift).filter(
                    work_date__gte=start, work_date__lt=start + timedelta(days=7)
                )
                diameter_output = Counter()
                for work_date, shift_label, quantity in closes_by_shift.values_list("work_date", "shift").annotate(qty=Sum("quantity")):
                    diameter_output[work_date, output_shift(shift_label)] += quantity
                diameter_series = weekly_series(dates, today, config.days, diameter_output, diameter_target, daily=True)

        if chosen_day:
            runs = runs.filter(work_date=chosen_day)
        shift_options = list(runs.exclude(shift="").order_by("shift").values_list("shift", flat=True).distinct())
        if shift not in shift_options:
            shift = ""
        if shift:
            runs = runs.filter(shift=shift)
        hours = config.hours * (1 if shift else config.shifts) * (1 if chosen_day else config.days)
        output = defaultdict(int)
        for code, quantity in runs.values_list("work_item__machine__code").annotate(qty=Sum("quantity")):
            output[configured_machine_code(code, config)] += quantity
        for code in sorted(config.machines.keys() | output.keys()):
            machine = config.machines.get(code)
            target = machine["rate"] * hours * int(machine["enabled"]) if machine else None
            if target is not None and target > 0:
                machine_rows.append((code, target, output[code], 100 * output[code] / target))
    else:
        dates = []
    weekly_machines = []
    for code in machine_options:
        limit = machine_limits.get(code)
        daily_output = machine_daily[code]
        produced = daily_output.total() if start else None
        used = 100 * produced / limit if produced is not None and limit else None
        by_shift = Counter()
        for (_, shift_key), quantity in daily_output.items():
            by_shift[shift_key] += quantity
        weekly_machines.append((code, limit, produced, used, by_shift["a"], by_shift["b"], by_shift["other"]))
    recent_closes = ProductionClose.objects.select_related(
        "work_item__order__part", "work_item__machine"
    ).order_by("-closed_at")[:20]
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "operations/capacity.html", {
        "weeks": [(k, f"{v[1]} · {v[0]:%d/%m/%Y}–{(v[0] + timedelta(days=6)):%d/%m/%Y}" if v[0] else v[1])
                  for k, v in sorted(periods.items(), key=lambda item: item[0], reverse=True)],
        "week": selected, "label": label, "calendar_week": bool(start), "clients": sorted(clients.items(), key=lambda item: item[1]),
        "physical_week": physical,
        "week_monday": start, "week_sunday": dates[-1] if dates else None,
        "snapshot_at": snapshot_at,
        "client": client, "total": total, "customers": [(clients[k], v) for k, v in by_customer.items()],
        "available_orders": available_orders,
        "machine_series": machine_series, "machine_options": machine_options, "chart_machine": machine_code,
        "diameter_series": diameter_series, "diameter_options": diameter_options, "chart_diameter": chart_diameter,
        "diameter_daily_limit": Decimal(diameter_limit) / config.days,
        "capacity_workdays": config.days,
        "machine_other_output": any(row[-1] for row in machine_series),
        "diameter_other_output": any(row[-1] for row in diameter_series),
        "capacities": rows, "plant": plant, "pool": pool, "installed": installed,
        "recent_closes": recent_closes,
        "plant_gap": abs(plant["margin"]), "over_limits": [r["name"] for r in rows if r["over"]],
        "details": Paginator(closed_details if physical else details, 30).get_page(request.GET.get("page")),
        "params": params.urlencode(),
        "machines": machine_rows, "weekly_machines": weekly_machines,
        "dates": dates, "day": day, "shifts": shift_options, "shift": shift,
    })


class LimitsForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput)
    days = forms.IntegerField(label="Días por semana", min_value=1, max_value=7)
    shifts = forms.IntegerField(label="Turnos por día", min_value=1, max_value=4)
    hours = forms.IntegerField(label="Horas por turno", min_value=1, max_value=24)
    shared_limit = forms.IntegerField(label="Bolsa semanal de 5/16 y 1/4", min_value=0, max_value=100000000)
    plant_ceiling = forms.IntegerField(label="Tope operativo semanal (opcional)", min_value=0,
                                       max_value=100000000, required=False)
    extra_size = forms.CharField(label="Nuevo diámetro", required=False, max_length=120)
    extra_limit = forms.IntegerField(label="Nuevo límite semanal", required=False, min_value=0, max_value=100000000)

    def __init__(self, config, data=None):
        super().__init__(data, initial={k: getattr(config, k) for k in self.base_fields if hasattr(config, k)})
        self.sizes = sorted(config.diameters)
        self.codes = sorted(config.machines)
        self.size_fields = []
        self.machine_fields = []
        for i, size in enumerate(self.sizes):
            key = f"size_{i}"
            self.fields[key] = forms.IntegerField(label=size, min_value=0, max_value=100000000,
                                                  initial=config.diameters[size], required=False)
            self.size_fields.append(self[key])
        for i, code in enumerate(self.codes):
            machine = config.machines[code]
            rate, enabled = f"rate_{i}", f"enabled_{i}"
            self.fields[rate] = forms.IntegerField(label=f"Piezas por hora de {code}", min_value=1,
                                                   max_value=1000000, initial=machine["rate"])
            self.fields[enabled] = forms.BooleanField(label=f"{code} disponible", required=False, initial=machine["enabled"])
            self.machine_fields.append((code, self[rate], self[enabled]))

    def clean(self):
        values = super().clean()
        if values.get("hours", 0) * values.get("shifts", 0) > 24:
            raise forms.ValidationError("Los turnos de un día no pueden sumar más de 24 horas.")
        extra = values.get("extra_size")
        if extra:
            values["extra_size"] = diameter(extra)
            if values["extra_size"] in self.sizes:
                self.add_error("extra_size", "Este diámetro ya tiene un campo en la lista.")
            if values.get("extra_limit") is None:
                self.add_error("extra_limit", "Introduce el límite del nuevo diámetro.")
        elif values.get("extra_limit") is not None:
            self.add_error("extra_size", "Indica a qué diámetro corresponde este límite.")
        return values


@login_required
@module_required("line_dashboard")
@permission_required("operations.change_capacitysettings", raise_exception=True)
@require_http_methods(["GET", "POST"])
def settings_view(request):
    config = CapacitySettings.objects.get(pk=1)
    form = LimitsForm(config, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data
        changes = {k: values[k] for k in ("days", "shifts", "hours", "shared_limit", "plant_ceiling")}
        changes["diameters"] = {size: values[f"size_{i}"] for i, size in enumerate(form.sizes)}
        if values.get("extra_size"):
            changes["diameters"][values["extra_size"]] = values["extra_limit"]
        changes["machines"] = {code: {"rate": values[f"rate_{i}"], "enabled": values[f"enabled_{i}"]}
                               for i, code in enumerate(form.codes)}
        with transaction.atomic():
            saved = CapacitySettings.objects.filter(pk=1, revision=values["revision"]).update(
                **changes, revision=values["revision"] + 1)
            if saved:
                AuditEvent.objects.create(user=request.user, action="capacity.update", entity="CapacitySettings",
                                          entity_id="1", data={**changes, "revision": values["revision"] + 1})
                messages.success(request, "Se guardaron los límites de capacidad.")
                return redirect("capacity-settings")
        form.add_error(None, "Otra persona modificó los límites. Vuelve a abrir esta página para cargar los valores vigentes.")
    return render(request, "operations/capacity_settings.html", {"form": form})
