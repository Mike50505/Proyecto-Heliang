from django.db import migrations


def hide_incorrect_client_samples(apps, schema_editor):
    Part = apps.get_model('operations', 'Part')
    Order = apps.get_model('operations', 'ProductionOrder')
    Audit = apps.get_model('operations', 'AuditEvent')
    database = schema_editor.connection.alias
    for code in ('4P565548-1', '4P574005-1', '4P793021-1', '3P848961-1', '3P511822-1'):
        original = Part.objects.using(database).filter(number=code, client__name__iexact='DAIKIN', sample_base__isnull=True).first()
        duplicate = Part.objects.using(database).filter(number=f'{code} (MUESTRAS)',
            client__name__iexact='RHEEM CIP-3501', sample_base__isnull=True, in_universe_ramos=False).first()
        if original is None or duplicate is None:
            continue
        order_ids = list(Order.objects.using(database).filter(part_id=duplicate.pk).values_list('pk', flat=True))
        # The historical client and every production FK stay unchanged. Only the
        # catalog alias points to the user-confirmed correct original.
        Part.objects.using(database).filter(pk=duplicate.pk).update(sample_base_id=original.pk)
        Order.objects.using(database).filter(pk__in=order_ids).update(is_sample=True)
        Audit.objects.using(database).create(action='HIDE_INCORRECT_CLIENT_SAMPLE', entity='Part',
            entity_id=str(duplicate.pk), data={'number': duplicate.number, 'original_part_id': original.pk,
                'original_number': original.number, 'historical_client_id_preserved': duplicate.client_id,
                'preserved_order_ids': order_ids, 'reason': 'User confirmed DAIKIN originals are correct; hide RHEEM sample duplicates.'})


class Migration(migrations.Migration):
    dependencies = [('operations', '0018_normalize_new_sample_parts')]
    operations = [migrations.RunPython(hide_incorrect_client_samples, migrations.RunPython.noop)]
