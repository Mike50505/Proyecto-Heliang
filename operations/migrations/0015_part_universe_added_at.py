from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower


def backfill_universe_added_at(apps, schema_editor):
    Part = apps.get_model("operations", "Part")
    for part in Part.objects.filter(in_universe_ramos=True, universe_added_at__isnull=True).only("id", "updated_at"):
        Part.objects.filter(pk=part.pk).update(universe_added_at=part.updated_at)


class Migration(migrations.Migration):
    dependencies = [("operations", "0014_remove_part_description")]

    operations = [
        migrations.AddField(
            model_name="part",
            name="universe_added_at",
            field=models.DateTimeField(null=True, blank=True, db_index=True),
        ),
        migrations.RunPython(backfill_universe_added_at, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="part",
            constraint=models.UniqueConstraint(
                Lower("number"), condition=Q(in_universe_ramos=True),
                name="uq_universe_part_number_ci",
            ),
        ),
    ]
