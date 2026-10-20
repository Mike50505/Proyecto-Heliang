import re
import unicodedata
from django.db import migrations, models
import django.db.models.deletion


def link_legacy_samples(apps, schema_editor):
    Part = apps.get_model('operations', 'Part')
    Order = apps.get_model('operations', 'ProductionOrder')
    database = schema_editor.connection.alias
    parts = list(Part.objects.using(database).all())
    normalize = lambda value: unicodedata.normalize('NFKC', value).strip().upper()
    normal = {}
    for part in parts:
        if '(MUESTRAS)' not in normalize(part.number):
            normal.setdefault(normalize(part.number), []).append(part)
    for sample in parts:
        match = re.fullmatch(r'(.+?)\s*\(MUESTRAS\)(?:\s+.*)?', normalize(sample.number))
        if not match or sample.in_universe_ramos:
            continue
        matches = normal.get(match[1].strip(), [])
        if len(matches) != 1 or matches[0].client_id != sample.client_id:
            continue
        Part.objects.using(database).filter(pk=sample.pk).update(sample_base_id=matches[0].pk)
        # Keep every original FK, quantity, balance, weight, timestamp and inventory row.
        Order.objects.using(database).filter(part_id=sample.pk).update(is_sample=True)


class Migration(migrations.Migration):
    dependencies = [('operations', '0016_moduleaccess_reports_delete_closes')]
    operations = [
        migrations.AddField(model_name='part', name='sample_base', field=models.ForeignKey(
            to='operations.part', null=True, blank=True, editable=False,
            on_delete=django.db.models.deletion.PROTECT, related_name='legacy_sample_parts')),
        migrations.AddField(model_name='productionorder', name='is_sample', field=models.BooleanField(
            default=False, verbose_name='Muestra', help_text='En órdenes nuevas, una muestra requiere 5 piezas. Editar esta marca conserva la cantidad existente.')),
        migrations.RunPython(link_legacy_samples, migrations.RunPython.noop),
    ]
