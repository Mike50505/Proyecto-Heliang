from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0007_paused_work")]

    operations = [
        migrations.AlterField(
            model_name="workinprocess",
            name="status",
            field=models.CharField(
                choices=[("ACTIVE", "Procesando"), ("CLOSED", "Cerrada")],
                default="ACTIVE",
                max_length=12,
            ),
        ),
    ]
