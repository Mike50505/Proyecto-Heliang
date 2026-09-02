from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_people(apps, schema_editor):
    Employee = apps.get_model("operations", "Employee")
    ModuleAccess = apps.get_model("operations", "ModuleAccess")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    admin = User.objects.filter(username="admin", is_superuser=True).first()
    if admin is None:
        admin = User.objects.filter(is_superuser=True).order_by("pk").first()

    employee_users = {}
    for employee in Employee.objects.exclude(user_id=None):
        employee_users[employee.pk] = employee.user_id
        access, _ = ModuleAccess.objects.get_or_create(user_id=employee.user_id)
        access.payroll_number = employee.payroll_number
        access.save(update_fields=["payroll_number"])

    employee_1303 = Employee.objects.filter(payroll_number="1303").first()
    if admin:
        access, _ = ModuleAccess.objects.get_or_create(user_id=admin.pk)
        access.payroll_number = "1303"
        access.save(update_fields=["payroll_number"])
        if employee_1303:
            employee_users[employee_1303.pk] = admin.pk

    mappings = (
        ("ProductionOrder", "loaded_by_id", "loaded_by_user_id"),
        ("WorkInProcess", "started_by_id", "started_by_user_id"),
        ("ProductionClose", "closed_by_id", "closed_by_user_id"),
        ("Movement", "employee_id", "employee_user_id"),
    )
    for model_name, old_field, new_field in mappings:
        model = apps.get_model("operations", model_name)
        for old_employee_id, user_id in employee_users.items():
            model.objects.filter(**{old_field: old_employee_id}).update(**{new_field: user_id})

    keep_user_ids = set(employee_users.values())
    if admin:
        keep_user_ids.add(admin.pk)
    User.objects.exclude(pk__in=keep_user_ids).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("operations", "0004_client_external_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="moduleaccess", name="payroll_number",
            field=models.CharField(blank=True, max_length=30, null=True, unique=True,
                                   verbose_name="número de nómina"),
        ),
        migrations.AddField(
            model_name="productionorder", name="loaded_by_user",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="workinprocess", name="started_by_user",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="productionclose", name="closed_by_user",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="movement", name="employee_user",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(migrate_people, migrations.RunPython.noop),
        migrations.RemoveField(model_name="productionorder", name="loaded_by"),
        migrations.RemoveField(model_name="workinprocess", name="started_by"),
        migrations.RemoveField(model_name="productionclose", name="closed_by"),
        migrations.RemoveField(model_name="movement", name="employee"),
        migrations.DeleteModel(name="Employee"),
        migrations.RenameField(model_name="productionorder", old_name="loaded_by_user", new_name="loaded_by"),
        migrations.RenameField(model_name="workinprocess", old_name="started_by_user", new_name="started_by"),
        migrations.RenameField(model_name="productionclose", old_name="closed_by_user", new_name="closed_by"),
        migrations.RenameField(model_name="movement", old_name="employee_user", new_name="employee"),
        migrations.AlterField(
            model_name="workinprocess", name="started_by",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="started_work", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="productionclose", name="closed_by",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="production_closes", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="productionorder", name="loaded_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="movement", name="employee",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    to=settings.AUTH_USER_MODEL),
        ),
    ]
