from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0009_productionorder_priority")]

    operations = [
        migrations.AddField(
            model_name="moduleaccess",
            name="universe",
            field=models.BooleanField(default=False, verbose_name="Universo Ramos Arizpe"),
        ),
    ]
