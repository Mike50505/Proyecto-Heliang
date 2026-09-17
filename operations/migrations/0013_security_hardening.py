from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("operations", "0012_concurrency_and_order_states"),
    ]

    operations = [
        migrations.AddField(
            model_name="moduleaccess", name="universe_edit",
            field=models.BooleanField(default=False, verbose_name="editar Universo Ramos Arizpe"),
        ),
        migrations.AddField(
            model_name="moduleaccess", name="universe_import",
            field=models.BooleanField(default=False, verbose_name="importar Universo Ramos Arizpe"),
        ),
        migrations.AlterField(
            model_name="moduleaccess", name="universe",
            field=models.BooleanField(default=False, verbose_name="consultar Universo Ramos Arizpe"),
        ),
        migrations.CreateModel(
            name="ProgramImportPreview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField(editable=False, unique=True)),
                ("payload", models.JSONField()),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="LoginThrottle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=64, unique=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("window_started_at", models.DateTimeField()),
                ("blocked_until", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.AddConstraint(model_name="inventory", constraint=models.CheckConstraint(condition=models.Q(("surplus__gte", 0)), name="inventory_surplus_nonnegative")),
        migrations.AddConstraint(model_name="inventory", constraint=models.CheckConstraint(condition=models.Q(("real__gte", 0)), name="inventory_real_nonnegative")),
        migrations.AddConstraint(model_name="inventorybucket", constraint=models.CheckConstraint(condition=models.Q(("quantity__gte", 0)), name="bucket_quantity_nonnegative")),
        migrations.AddConstraint(model_name="productionorder", constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="order_quantity_positive")),
        migrations.AddConstraint(model_name="productionorder", constraint=models.CheckConstraint(condition=models.Q(("remaining_quantity__gte", 0)), name="order_remaining_nonnegative")),
        migrations.AddConstraint(model_name="productionorder", constraint=models.CheckConstraint(condition=models.Q(("remaining_quantity__lte", models.F("quantity"))), name="order_remaining_lte_quantity")),
        migrations.AddConstraint(model_name="workinprocess", constraint=models.CheckConstraint(condition=models.Q(("initial_quantity__gt", 0)), name="work_initial_positive")),
        migrations.AddConstraint(model_name="workinprocess", constraint=models.CheckConstraint(condition=models.Q(("remaining_quantity__gte", 0)), name="work_remaining_nonnegative")),
        migrations.AddConstraint(model_name="workinprocess", constraint=models.CheckConstraint(condition=models.Q(("remaining_quantity__lte", models.F("initial_quantity"))), name="work_remaining_lte_initial")),
        migrations.AddConstraint(model_name="productionclose", constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="close_quantity_positive")),
        migrations.AddConstraint(model_name="productionclose", constraint=models.CheckConstraint(condition=models.Q(("weight_kg__gte", 0)), name="close_weight_nonnegative")),
    ]
