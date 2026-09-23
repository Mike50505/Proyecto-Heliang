from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0013_security_hardening")]

    operations = [
        migrations.RemoveField(model_name="part", name="description"),
        migrations.AddField(
            model_name="part", name="in_universe_ramos",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
