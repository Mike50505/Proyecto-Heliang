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
from django.db.models import Q, Sum, Value
from django.db.models.functions import Greatest, TruncDate
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .access import module_required
from .formatting import diameter_category, diameter_category_sort_key
from .models import AuditEvent, CapacitySettings, Machine, ProductionClose, ProductionOrder


WEEK = re.compile(r"(?:(\d{4})[ -]?)?(?:SEMANA|SEM|WK|W|S)?\s*0?(\d{1,2})(?:[ /-]+(\d{4}))?", re.I)
SHARED = ("5/16", "1/4")
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


def output_shift(label):
    name = " ".join(label.casefold().split()).removeprefix("turno ")
    return name if name in ("a", "b") else "other"


def weekly_series(dates, today, workdays, daily_output, target):
    totals = Counter()
    rows = []
    for index, day in enumerate(dates, start=1):
        totals.update({shift: daily_output[day, shift] for shift in OUTPUT_SHIFTS})
        expected = Decimal(target) * min(index, workdays) / workdays if target is not None else None
        actual = totals.total() if day <= today else None
        quantities = [totals[shift] if day <= today else None for shift in OUTPUT_SHIFTS]
        rows.append((day, actual, expected, *quantities))
    return rows


def configured_machine_code(code, config):
    pieces = code.split()
    return pieces[0] if pieces and pieces[0] in config.machines else code


@login_required
@module_required("line_dashboard")
@never_cache
def dashboard(request):
    config = CapacitySettings.objects.get(pk=1)
    snapshot_at = timezone.now()
    today = timezone.localdate(snapshot_at)
    current = today - timedelta(days=today.weekday())
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
    selected = request.GET.get("week", current.isoformat())
    if selected not in periods:
        selected = current.isoformat()
    start, label = periods[selected]
    end = midnight(start + timedelta(days=7)) if start else None
    cutoff = min(snapshot_at, end) if end else snapshot_at
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
    sizes = list(config.diameters) + sorted((planned.keys() | carry.keys()) - config.diameters.keys())
    rows = [capacity_row(s, config.diameters.get(s), planned[s], carry[s]) for s in sizes
            if s in config.diameters or planned[s] or carry[s]]
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
    registered_machines = {configured_machine_code(code, config) for code in
                           Machine.objects.filter(active=True).values_list("code", flat=True)}
    machine_options = sorted(machine_limits.keys() | registered_machines)
    diameter_options = sorted(by_diameter, key=diameter_category_sort_key)
    machine_code = request.GET.get("chart_machine", "")
    chart_diameter = request.GET.get("chart_diameter", "")
    if chart_diameter not in by_diameter:
        chart_diameter = ""
    day = request.GET.get("day", "")
    shift = request.GET.get("shift", "")
    shift_options = []
    if start:
        dates = [start + timedelta(days=i) for i in range(7)]
        chosen_day = next((d for d in dates if d.isoformat() == day), None)
        runs = ProductionClose.objects.filter(closed_at__gte=midnight(start), closed_at__lt=cutoff)
        for code, work_date, shift_label, quantity in runs.annotate(work_date=TruncDate("closed_at")).values_list(
            "work_item__machine__code", "work_date", "shift"
        ).annotate(qty=Sum("quantity")):
            machine_daily[configured_machine_code(code, config)][work_date, output_shift(shift_label)] += quantity
        machine_options = sorted(machine_limits.keys() | registered_machines | machine_daily.keys())
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
        machine_series = weekly_series(dates, today, config.days, machine_output, machine_target)

        matching_orders = [order_id for order_id, size in selected_parts.items()
                           if not chart_diameter or size == chart_diameter]
        diameter_target = by_diameter[chart_diameter].planned if chart_diameter else total.planned
        if diameter_target:
            # Credit production from before the selected week to its opening day, as in the program total.
            closes_by_shift = ProductionClose.objects.filter(work_item__order_id__in=matching_orders,
                                                               closed_at__lt=cutoff)
            closes_by_shift = closes_by_shift.annotate(work_date=Greatest(TruncDate("closed_at"), Value(start)))
            diameter_output = Counter()
            for work_date, shift_label, quantity in closes_by_shift.values_list("work_date", "shift").annotate(qty=Sum("quantity")):
                diameter_output[work_date, output_shift(shift_label)] += quantity
            diameter_series = weekly_series(dates, today, config.days, diameter_output, diameter_target)

        if chosen_day:
            runs = runs.filter(closed_at__date=chosen_day)
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
            machine_rows.append((code, target, output[code], 100 * output[code] / target if target else None))
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
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "operations/capacity.html", {
        "weeks": [(k, v[1]) for k, v in sorted(periods.items(), key=lambda item: item[0], reverse=True)],
        "week": selected, "label": label, "calendar_week": bool(start), "clients": sorted(clients.items(), key=lambda item: item[1]),
        "snapshot_at": snapshot_at,
        "client": client, "total": total, "customers": [(clients[k], v) for k, v in by_customer.items()],
        "available_orders": available_orders,
        "machine_series": machine_series, "machine_options": machine_options, "chart_machine": machine_code,
        "diameter_series": diameter_series, "diameter_options": diameter_options, "chart_diameter": chart_diameter,
        "machine_other_output": any(row[-1] for row in machine_series),
        "diameter_other_output": any(row[-1] for row in diameter_series),
        "capacities": rows, "plant": plant, "pool": pool, "installed": installed,
        "plant_gap": abs(plant["margin"]), "over_limits": [r["name"] for r in rows if r["over"]],
        "details": Paginator(details, 30).get_page(request.GET.get("page")), "params": params.urlencode(),
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
