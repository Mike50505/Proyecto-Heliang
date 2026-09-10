from django.db import migrations, models


def enable_universe(apps, schema_editor):
    ModuleAccess = apps.get_model("operations", "ModuleAccess")
    ModuleAccess.objects.all().update(universe=True)


class Migration(migrations.Migration):
    dependencies = [("operations", "0010_moduleaccess_universe")]

    operations = [
        migrations.AlterField(
            model_name="moduleaccess",
            name="universe",
            field=models.BooleanField(default=True, verbose_name="Universo Ramos Arizpe"),
        ),
        migrations.RunPython(enable_universe, migrations.RunPython.noop),
    ]
