from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('operations', '0020_link_corrected_carrier_part')]
    operations = [
        migrations.AlterField(model_name='client', name='name', field=models.CharField(max_length=150)),
        migrations.AlterField(model_name='part', name='number', field=models.CharField(max_length=120, unique=True, verbose_name='número de parte')),
        migrations.AlterField(model_name='part', name='diameter', field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name='part', name='central_id', field=models.UUIDField(blank=True, editable=False, null=True, unique=True)),
        migrations.AddField(model_name='part', name='central_payload', field=models.JSONField(blank=True, default=dict, editable=False)),
        migrations.AddField(model_name='part', name='local_catalog_snapshot', field=models.JSONField(blank=True, default=dict, editable=False)),
        migrations.AddField(model_name='part', name='catalog_available', field=models.BooleanField(db_index=True, default=True, editable=False)),
        migrations.CreateModel(name='UniverseSyncState', fields=[
            ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ('enabled', models.BooleanField(default=False)),
            ('source_url', models.URLField(blank=True)),
            ('credential_fingerprint', models.CharField(blank=True, max_length=64)),
            ('cursor', models.TextField(blank=True)),
            ('policy_version', models.PositiveIntegerField(default=1)),
            ('include_samples', models.BooleanField(default=True)),
            ('last_success_at', models.DateTimeField(blank=True, null=True)),
            ('last_error', models.CharField(blank=True, max_length=240)),
            ('part_count', models.PositiveIntegerField(default=0)),
        ]),
    ]
