from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0006_programimportreceipt")]

    operations = [
        migrations.AlterField(
            model_name="workinprocess",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Procesando"),
                    ("PAUSED", "Pausada"),
                    ("CLOSED", "Cerrada"),
                ],
                default="ACTIVE",
                max_length=12,
            ),
        ),
    ]
