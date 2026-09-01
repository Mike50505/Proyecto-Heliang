from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_existing_access(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    ModuleAccess = apps.get_model("operations", "ModuleAccess")
    ModuleAccess.objects.bulk_create(
        [ModuleAccess(user_id=user.pk) for user in User.objects.all()], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("operations", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="ModuleAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("program_loading", models.BooleanField(default=False, verbose_name="cargar programas")),
                ("heliang", models.BooleanField(default=False, verbose_name="Heliang · máquinas automáticas")),
                ("inventory", models.BooleanField(default=False, verbose_name="consultar inventario")),
                ("surplus", models.BooleanField(default=False, verbose_name="material sobrante")),
                ("process_material", models.BooleanField(default=False, verbose_name="material en proceso")),
                ("reports", models.BooleanField(default=False, verbose_name="reportes")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                               related_name="module_access", to=settings.AUTH_USER_MODEL,
                                               verbose_name="usuario")),
            ],
            options={"verbose_name": "acceso a módulos", "verbose_name_plural": "accesos a módulos"},
        ),
        migrations.RunPython(create_existing_access, migrations.RunPython.noop),
    ]
