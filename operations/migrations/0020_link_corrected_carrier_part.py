from django.db import migrations


def link_corrected_carrier_part(apps, schema_editor):
    Part = apps.get_model('operations', 'Part')
    Order = apps.get_model('operations', 'ProductionOrder')
    Audit = apps.get_model('operations', 'AuditEvent')
    database = schema_editor.connection.alias
    parts = Part.objects.using(database)
    original = parts.filter(number='48TM004286B', sample_base__isnull=True).first()
    duplicate = parts.filter(number='48TM004286').first()
    # Other installations may not have both records. Never create a new part here.
    if original is None or duplicate is None:
        return
    if duplicate.sample_base_id == original.pk:
        return
    if duplicate.sample_base_id is not None or duplicate.client_id != original.client_id:
        raise RuntimeError('Review the 48TM004286 alias/client before linking it to 48TM004286B.')
    order_ids = list(Order.objects.using(database).filter(part_id=duplicate.pk)
                     .values_list('pk', flat=True))
    # Keep IDs, quantities, timestamps, inventories, and every historical FK intact.
    parts.filter(pk=duplicate.pk).update(sample_base_id=original.pk)
    Audit.objects.using(database).create(
        action='LINK_CORRECTED_PART', entity='Part', entity_id=str(duplicate.pk),
        data={'number': duplicate.number, 'original_part_id': original.pk,
              'original_number': original.number, 'preserved_order_ids': order_ids,
              'reason': 'User confirmed that 48TM004286 is a misspelling of 48TM004286B.'})


class Migration(migrations.Migration):
    dependencies = [('operations', '0019_hide_incorrect_client_samples')]
    operations = [migrations.RunPython(link_corrected_carrier_part, migrations.RunPython.noop)]
