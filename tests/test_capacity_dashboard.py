from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from operations.capacity import LimitsForm, midnight, week_start
from operations.models import (AuditEvent, CapacitySettings, Client, Machine, ModuleAccess, Part,
                              ProductionClose, ProductionOrder, WorkInProcess)


@pytest.fixture
def planner(client, django_user_model):
    user = django_user_model.objects.create_user("planeacion")
    ModuleAccess.objects.update_or_create(user=user, defaults={"line_dashboard": True})
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_capacity_with_carry_and_client_filter(client, planner):
    alpha = Client.objects.create(code="A", name="Alpha")
    beta = Client.objects.create(code="B", name="Beta")
    a = Part.objects.create(number="A-1", diameter="A - 1/2", client=alpha)
    b = Part.objects.create(number="B-1", diameter="0.5", client=beta)
    monday = date(2025, 12, 29)
    assert week_start("S01", monday) == monday

    def order(folio, program, part, qty):
        return ProductionOrder.objects.create(folio=folio, program=program, part=part,
                                              quantity=qty, remaining_quantity=qty)

    prior = order("old", "2025-W52", a, 6000)
    selected = order("new", "2026-W01", a, 10000)
    order("other", "2026-W01", b, 5200)
    machine = Machine.objects.create(code="INT22T05 1-2")
    Machine.objects.create(code="HEL-99")
    for o in (prior, selected):
        work = WorkInProcess.objects.create(folio=o.folio, order=o, machine=machine, initial_quantity=o.quantity,
                                           remaining_quantity=0, status="CLOSED", started_at=midnight(monday))
        cuts = [(1000, -1, "A")] if o == prior else [(500, -1, "A"), (4500, 1, "Turno A"), (2500, 1, "Turno B"), (500, 1, "")]
        for i, (qty, offset, shift) in enumerate(cuts):
            ProductionClose.objects.create(folio=f"{o.folio}-{i}", work_item=work, quantity=qty, shift=shift,
                                           closed_at=midnight(monday + timedelta(days=offset)))
    response = client.get(reverse("capacity-dashboard"), {
        "week": monday.isoformat(), "client": alpha.pk, "chart_machine": "INT22T05", "chart_diameter": "1/2",
    })
    assert "no-store" in response.headers["Cache-Control"]
    html = response.content.decode()
    assert 'data-cap-list="diameter-capacity"' in html
    assert 'cap-diameter-capacity-row cap-over' in html
    ctx = response.context
    assert ctx["total"].percent == 80
    assert ctx["total"].available == 1
    assert ctx["plant"]["limit"] == 129600
    half = next(row for row in ctx["capacities"] if row["name"] == "1/2")
    assert (half["carry"], half["planned"], half["load"], half["margin"]) == (5000, 15200, 20200, -1000)
    assert half["over"]
    assert ctx["pool"]["limit"] == 25600
    assert next(row for row in ctx["machines"] if row[0] == "INT22T05")[2] == 7500
    assert ctx["machine_series"][0] == (monday, 0, 1920, 0, 0, 0)
    assert ctx["machine_series"][-1][1:] == (7500, 9600, 4500, 2500, 500)
    weekly_machines = {code: tuple(values) for code, *values in ctx["weekly_machines"]}
    assert weekly_machines["INT22T05"] == (9600, 7500, Decimal(750000) / 9600, 4500, 2500, 500)
    assert weekly_machines["INT32T02"] == (0, 0, None, 0, 0, 0)
    assert weekly_machines["HEL-99"] == (None, 0, None, 0, 0, 0)
    assert ctx["diameter_series"][0] == (monday, 500, 2000, 500, 0, 0)
    assert ctx["diameter_series"][-1][1:] == (8000, 10000, 5000, 2500, 500)
    assert ctx["machine_other_output"] and ctx["diameter_other_output"]
    assert ctx["available_orders"] == [("new", "A-1", "Alpha", 10000)]


@pytest.mark.django_db
def test_physical_week_uses_local_closure_dates_across_programs(client, planner):
    monday = date(2025, 12, 29)
    first = midnight(monday)
    next_monday = midnight(monday + timedelta(days=7))
    alpha = Client.objects.create(code="A", name="Alpha")
    beta = Client.objects.create(code="B", name="Beta")
    machine = Machine.objects.create(code="INT22T05")

    for index, (customer, program, closed_at, qty, shift) in enumerate([
        (alpha, "2026-W01", first - timedelta(minutes=1), 100, "Turno A"),
        (alpha, "2026-W01", first, 200, "Turno A"),
        (beta, "Orden especial anterior", next_monday - timedelta(minutes=1), 400, "Turno B"),
        (beta, "2025-W52", next_monday, 800, "Turno B"),
    ]):
        part = Part.objects.create(number=f"P-{index}", diameter="1/2", client=customer)
        order = ProductionOrder.objects.create(
            folio=f"O-{index}", program=program, part=part, quantity=1000, remaining_quantity=1000,
        )
        work = WorkInProcess.objects.create(
            folio=f"W-{index}", order=order, machine=machine, initial_quantity=1000,
            remaining_quantity=0, status="CLOSED", started_at=closed_at,
        )
        ProductionClose.objects.create(
            folio=f"C-{index}", work_item=work, quantity=qty, shift=shift, closed_at=closed_at,
        )

    url = reverse("capacity-dashboard")
    response = client.get(url, {"week_mode": "physical", "week": monday.isoformat(), "chart_diameter": "1/2"})
    ctx = response.context
    assert ctx["physical_week"] and ctx["week_monday"] == monday
    assert ctx["week_sunday"] == monday + timedelta(days=6)
    assert (ctx["total"].planned, ctx["total"].done, ctx["total"].pending) == (2000, 600, 1700)
    assert ctx["plant"]["load"] == 600
    assert ctx["diameter_series"][0][1:] == (200, 3840, 200, 0, 0)
    assert ctx["diameter_series"][-1][1:] == (600, 19200, 200, 400, 0)
    assert [row[1] for row in ctx["details"]] == ["O-2", "O-1"]
    assert (next_monday.date().isoformat(), "Semana 02 · 2026") in ctx["weeks"]
    assert ("program:Orden especial anterior", "Orden especial anterior") not in ctx["weeks"]

    filtered = client.get(url, {"week_mode": "physical", "week": monday.isoformat(), "client": beta.pk}).context
    assert filtered["total"].done == 400
    assert filtered["plant"]["load"] == 600
    assert [row[1] for row in filtered["details"]] == ["O-2"]
    assert client.get(url, {"week": monday.isoformat()}).context["total"].done == 300


@pytest.mark.django_db
def test_shared_pool_unknown_size_and_unallocated_work(client, planner):
    config = CapacitySettings.objects.get(pk=1)
    config.diameters["5/8"] = 0
    config.save(update_fields=["diameters"])
    for i, (size, qty) in enumerate([("5/16", 15000), ("1/4", 14000), ("7mm", 2000)]):
        part = Part.objects.create(number=f"PART-{i}", diameter=size)
        ProductionOrder.objects.create(folio=f"F-{i}", program="Lote especial", part=part,
                                       quantity=qty, remaining_quantity=0, status="ALLOCATED")
    response = client.get(reverse("capacity-dashboard"), {"week": "program:Lote especial"})
    ctx = response.context
    assert ctx["total"].available == 0
    assert ctx["total"].pending == 31000
    assert ctx["pool"]["over"] and ctx["pool"]["margin"] == -3400
    assert not ctx["plant"]["over"]
    assert not ctx["calendar_week"]
    unknown = next(row for row in ctx["capacities"] if row["name"] == "7 mm")
    assert unknown["load"] == 2000 and unknown["limit"] is None
    html = response.content.decode()
    assert 'role="rowheader" title="7 mm"' not in html
    assert 'role="rowheader" title="5/8"' in html


@pytest.mark.django_db
def test_edit_limits_atomic_and_guarded(client, planner):
    url = reverse("capacity-settings")
    assert client.get(url).status_code == 403
    planner.user_permissions.add(Permission.objects.get(codename="change_capacitysettings"))
    config = CapacitySettings.objects.get(pk=1)
    form = LimitsForm(config)
    data = {f.name: f.value() for f in form if f.value() not in (False, None)}
    data.update(days=4, extra_size="9 mm", extra_limit=2000)
    assert client.get(url).status_code == 200
    assert f'href="{url}">Planeación</a>' in client.get(reverse("dashboards")).content.decode()
    assert "Administrar límites" not in client.get(reverse("capacity-dashboard")).content.decode()
    assert client.post(url, {**data, "hours": 18}).status_code == 200
    config.refresh_from_db()
    assert config.days == 5
    saved = client.post(url, data)
    assert saved.status_code == 302 and saved.url == url
    config.refresh_from_db()
    assert config.diameters["9 mm"] == 2000
    assert config.days == 4
    stale = {**data, "days": 3, "extra_size": "", "extra_limit": ""}
    assert "Otra persona" in client.post(url, stale).content.decode()
    assert AuditEvent.objects.filter(action="capacity.update").count() == 1
    assert client.get(reverse("capacity-dashboard")).context["plant"]["limit"] == 103680
