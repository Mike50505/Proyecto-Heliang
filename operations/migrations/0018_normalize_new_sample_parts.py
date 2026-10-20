import re
import unicodedata
from collections import Counter
from fractions import Fraction
from django.db import migrations, models


def normalize_new_samples(apps, schema_editor):
    Part = apps.get_model('operations', 'Part')
    Order = apps.get_model('operations', 'ProductionOrder')
    Audit = apps.get_model('operations', 'AuditEvent')
    database = schema_editor.connection.alias
    parts = list(Part.objects.using(database).all())
    normalize = lambda value: unicodedata.normalize('NFKC', value).strip().upper()
    known = {normalize(part.number) for part in parts}
    candidates = []
    for part in parts:
        if part.sample_base_id or part.in_universe_ramos or part.legacy_number:
            continue
        match = re.fullmatch(r'(.+?)\s*\(MUESTRAS\)(?:\s+(.+))?', part.number.strip(), re.I)
        if match and normalize(match[1]) not in known:
            candidates.append((part, match[1].strip(), (match[2] or '').strip()))
    counts = Counter(normalize(base) for _, base, _ in candidates)
    for part, base, suffix in candidates:
        if counts[normalize(base)] != 1:
            continue
        before = {'number': part.number, 'diameter': part.diameter}
        diameter = part.diameter
        if not diameter and re.fullmatch(r'(?:\d+\s+)?\d+/\d+|\d+(?:\.\d+)?', suffix):
            try:
                if Fraction(suffix) > 0:
                    diameter = suffix
            except (ValueError, ZeroDivisionError):
                pass
        order_ids = list(Order.objects.using(database).filter(part_id=part.pk).values_list('pk', flat=True))
        Part.objects.using(database).filter(pk=part.pk).update(number=base, diameter=diameter, legacy_number=part.number)
        # Preserve quantities, balances, client, timestamps, weights and all original FKs.
        Order.objects.using(database).filter(pk__in=order_ids).update(is_sample=True)
        Audit.objects.using(database).create(action='NORMALIZE_SAMPLE_PART', entity='Part', entity_id=str(part.pk), data={
            'before': before, 'after': {'number': base, 'diameter': diameter},
            'preserved_order_ids': order_ids, 'same_part_id': part.pk,
            'diameter_source': 'legacy_number' if diameter != part.diameter else 'unchanged',
        })


class Migration(migrations.Migration):
    dependencies = [('operations', '0017_order_samples')]
    operations = [
        migrations.AddField(model_name='part', name='legacy_number', field=models.CharField(
            max_length=80, blank=True, default='', editable=False, db_index=True)),
        migrations.RunPython(normalize_new_samples, migrations.RunPython.noop),
    ]
