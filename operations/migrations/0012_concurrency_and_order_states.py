from django.db import migrations, models
from django.db.models import Q


def mark_allocated_orders(apps, schema_editor):
    ProductionOrder = apps.get_model("operations", "ProductionOrder")
    WorkInProcess = apps.get_model("operations", "WorkInProcess")
    active_order_ids = WorkInProcess.objects.filter(
        status="ACTIVE", order__status="COMPLETE"
    ).values_list("order_id", flat=True)
    ProductionOrder.objects.filter(pk__in=active_order_ids).update(status="ALLOCATED")


class Migration(migrations.Migration):
    dependencies = [("operations", "0011_enable_universe_access")]

    operations = [
        migrations.AlterField(
            model_name="productionorder",
            name="status",
            field=models.CharField(
                choices=[
                    ("OPEN", "Abierta"),
                    ("ALLOCATED", "Asignada"),
                    ("COMPLETE", "Completada"),
                    ("CANCELLED", "Cancelada"),
                ],
                default="OPEN",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="FolioCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=100, unique=True)),
                ("next_value", models.PositiveBigIntegerField(default=1)),
            ],
        ),
        migrations.RunPython(mark_allocated_orders, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="workinprocess",
            constraint=models.UniqueConstraint(
                condition=Q(status="ACTIVE"), fields=("machine",),
                name="uq_active_work_per_machine"),
        ),
    ]
