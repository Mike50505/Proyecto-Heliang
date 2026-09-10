from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0008_remove_paused_status")]

    operations = [
        migrations.AddField(
            model_name="productionorder",
            name="priority",
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
