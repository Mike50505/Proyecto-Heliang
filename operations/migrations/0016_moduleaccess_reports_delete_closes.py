from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0015_part_universe_added_at")]

    operations = [
        migrations.AddField(
            model_name="moduleaccess", name="reports_delete_closes",
            field=models.BooleanField(default=False, verbose_name="eliminar cierres desde reportes"),
        ),
    ]
