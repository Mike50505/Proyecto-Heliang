from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0002_moduleaccess")]
    operations = [
        migrations.AddField(
            model_name="moduleaccess",
            name="line_dashboard",
            field=models.BooleanField(default=False, verbose_name="tablero visual de línea"),
        ),
    ]
