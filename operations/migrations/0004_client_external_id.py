from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0003_moduleaccess_line_dashboard")]

    operations = [
        migrations.AddField(
            model_name="client",
            name="external_id",
            field=models.CharField(blank=True, db_index=True, max_length=30, verbose_name="ID cliente"),
        ),
    ]
