import hashlib
import json
from decimal import Decimal
from django.db import migrations, models


def seed_receipts(apps, schema_editor):
    Order = apps.get_model("operations", "ProductionOrder")
    Event = apps.get_model("operations", "AuditEvent")
    Receipt = apps.get_model("operations", "ProgramImportReceipt")
    alias = schema_editor.connection.alias

    def remember(values):
        fingerprint = hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()
        Receipt.objects.using(alias).get_or_create(fingerprint=fingerprint)

    for order in Order.objects.using(alias).select_related("part").iterator():
        remember([order.program.strip(), order.part.number.strip(),
                  format(Decimal(order.quantity).normalize(), "f"), order.part.client_id,
                  order.line.strip(), order.required_date.isoformat() if order.required_date else ""])

    # Folios could be reused after deletion. Match the most recent preceding
    # load in chronological order, never a later load of the same folio.
    loads = {}
    events = Event.objects.using(alias).filter(
        entity="ProductionOrder", action__in=["LOAD_PROGRAM", "DELETE_PROGRAM"]
    ).order_by("created_at", "pk")
    for event in events.iterator():
        if event.action == "LOAD_PROGRAM":
            loads[event.entity_id] = event.data
        else:
            data = loads.pop(event.entity_id, None)
            if data and all(key in data for key in ("program", "part", "quantity")):
                remember([data["program"].strip(), data["part"].strip(),
                          format(Decimal(data["quantity"]).normalize(), "f")])


class Migration(migrations.Migration):
    dependencies = [("operations", "0005_unify_users_and_employees")]
    operations = [
        migrations.CreateModel(
            name="ProgramImportReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fingerprint", models.CharField(max_length=64, unique=True)),
            ],
        ),
        migrations.RunPython(seed_receipts, migrations.RunPython.noop),
    ]
