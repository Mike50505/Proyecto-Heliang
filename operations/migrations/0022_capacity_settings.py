from django.db import migrations, models


def seed_capacity(apps, schema_editor):
    settings = apps.get_model("operations", "CapacitySettings")
    rates = {
        "INT22T04": 120, "INT22T05": 120, "INT22T06": 90,
        "INT22T07": 120, "INT22T08": 120, "INTAL010": 320,
        "INTAL011": 320, "INTAL09": 320, "INT32T02": 90, "INT32R02": 90,
    }
    settings.objects.using(schema_editor.connection.alias).create(
        pk=1,
        diameters={"3/4": 19200, "1/2": 19200, "7/8": 14400, "3/8": 51200,
                   "5/16": 12800, "1/4": 12800, "5/8": None, "7 mm": None},
        machines={code: {"rate": rate, "enabled": code != "INT32T02"} for code, rate in rates.items()},
    )


class Migration(migrations.Migration):
    dependencies = [("operations", "0021_universe_ramos_connection")]
    operations = [
        migrations.CreateModel(
            name="CapacitySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("days", models.PositiveSmallIntegerField(default=5)),
                ("shifts", models.PositiveSmallIntegerField(default=2)),
                ("hours", models.PositiveSmallIntegerField(default=8)),
                ("shared_limit", models.PositiveIntegerField(default=25600)),
                ("plant_ceiling", models.PositiveIntegerField(blank=True, null=True)),
                ("diameters", models.JSONField(default=dict)),
                ("machines", models.JSONField(default=dict)),
                ("revision", models.PositiveIntegerField(default=1)),
            ],
            options={"verbose_name": "configuración de capacidad"},
        ),
        migrations.RunPython(seed_capacity, migrations.RunPython.noop),
    ]
