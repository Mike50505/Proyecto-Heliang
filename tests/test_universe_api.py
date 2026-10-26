from copy import deepcopy
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from operations.forms import ProductionOrderEditForm, SurplusMovementForm, ProcessMovementForm
from operations.models import (Client, Machine, Part, ProductionOrder, Movement, Inventory,
                               InventoryBucket, WorkInProcess, ProductionClose, UniverseSyncState)
from operations.services import close_production, create_program_order, resolve_program_client, start_production
from operations.universe_api import UniverseAPI, UniverseAPIError, ResyncRequired, synchronize_universe


class FakeAPI:
    def __init__(self, parts, events=(), policy=1, samples=True):
        self.parts = parts
        self.events = events
        self.policy = policy
        self.samples = samples
        self.catalogs = {'customers': [], 'destinations': [], 'boxes': [], 'sheet_colors': []}

    def get(self, path):
        if '/bootstrap/' in path:
            return {'parts_url': '/api/v1/parts/?policy_version=' + str(self.policy),
                    'changes_cursor': 'initial', 'include_samples': self.samples, 'policy_version': self.policy}
        if '/changes/' in path:
            return deepcopy({'results': self.events, 'next_cursor': 'final', 'has_more': False})
        if '/catalogs/' in path:
            return deepcopy(self.catalogs)
        if '/parts/?' in path:
            return deepcopy({'results': self.parts, 'count': len(self.parts), 'next': None})
        raise AssertionError('Unexpected API request: ' + path)


def remote(number='CANONICAL-001', **kwargs):
    return {'id': str(uuid4()), 'part_number': number, 'customer': 'Central customer',
            'diameter': '0.375', 'weight': '0.125000', 'active': True, 'is_sample': False,
            'version': 1, **kwargs}


@override_settings(UR_BASE_URL='https://universo.example', UR_API_KEY='test-only-token', UR_WEIGHT_UNIT='kg')
class UniverseAPITests(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(code='OLD', name='Historical customer', external_id='CD0082')
        self.part = Part.objects.create(number='CANONICAL-001', client=self.client_record,
            diameter='OLD', unit_weight_kg=Decimal('0.300000'), in_universe_ramos=True)
        self.row = remote()

    def sync(self, rows=None, **kwargs):
        return synchronize_universe(api=FakeAPI([self.row] if rows is None else rows, **kwargs))

    def test_initial_link_preserves_ids_all_history_and_original_metadata(self):
        before_part = Part.objects.values().get(pk=self.part.pk)
        order = ProductionOrder.objects.create(folio='OLD-ORDER', program='OLD', part=self.part,
            quantity=14000, remaining_quantity=13980)
        inv = Inventory.objects.create(part=self.part, real=50, surplus=8)
        InventoryBucket.objects.create(inventory=inv, kind='PROGRAM', name='OLD', quantity=5)
        Movement.objects.create(folio=order.folio, part=self.part, movement_type='PROGRAM',
            quantity=14000, occurred_at=timezone.now())
        models = (ProductionOrder, Movement, Inventory, InventoryBucket, WorkInProcess, ProductionClose)
        before = {model: list(model.objects.order_by('pk').values()) for model in models}
        result = self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.pk, before_part['id'])
        self.assertEqual(str(self.part.central_id), self.row['id'])
        self.assertEqual(self.part.client.name, self.row['customer'])
        self.assertEqual(self.part.diameter, self.row['diameter'])
        self.assertEqual(self.part.unit_weight_kg, Decimal(self.row['weight']))
        self.assertEqual(self.part.local_catalog_snapshot['client_id'], self.client_record.pk)
        self.assertEqual(self.part.local_catalog_snapshot['diameter'], before_part['diameter'])
        self.assertEqual(self.part.updated_at, before_part['updated_at'])
        for model in models:
            self.assertEqual(list(model.objects.order_by('pk').values()), before[model])
        self.assertEqual(result['available'], 1)
        self.assertTrue(UniverseSyncState.objects.get(pk=1).enabled)
        self.assertEqual(self.sync()['updated'], 0)
        self.assertEqual(Part.objects.count(), 1)

    def test_permissions_remove_and_restore_same_id_without_touching_existing_orders(self):
        self.row['is_sample'] = True
        self.sync()
        order = ProductionOrder.objects.create(folio='KEPT', program='OLD', part=self.part, quantity=16, remaining_quantity=11)
        before = ProductionOrder.objects.values().get(pk=order.pk)
        self.sync([], policy=2, samples=False)
        self.part.refresh_from_db()
        self.assertFalse(self.part.catalog_available)
        self.assertEqual(ProductionOrder.objects.values().get(pk=order.pk), before)
        with self.assertRaises(ValidationError):
            create_program_order(client_name='OLD', part_number=self.part.number, program='NEW', quantity=9)
        self.sync(policy=3)
        self.part.refresh_from_db()
        self.assertTrue(self.part.catalog_available)
        self.assertEqual(Part.objects.count(), 1)
        self.assertEqual(ProductionOrder.objects.values().get(pk=order.pk), before)

    def test_replays_changes_and_resolves_catalog_ids_before_commit(self):
        customer_id = str(uuid4())
        event = {**self.row, 'customer_id': customer_id, 'diameter': '0.5', 'version': 2}
        event.pop('customer')
        api = FakeAPI([self.row], [{'part_id': self.row['id'], 'excluded': False, 'part': event}])
        api.catalogs['customers'] = [{'id': customer_id, 'name': 'Updated central customer'}]
        synchronize_universe(api=api)
        self.part.refresh_from_db()
        self.assertEqual(self.part.client.name, 'Updated central customer')
        self.assertEqual(self.part.diameter, '0.5')
        self.assertEqual(UniverseSyncState.objects.get(pk=1).cursor, 'final')

    def test_network_failure_or_invalid_data_keeps_whole_previous_cache(self):
        self.sync()
        before = list(Part.objects.values())
        previous = UniverseSyncState.objects.values().get(pk=1)
        api = FakeAPI([{**self.row, 'diameter': 'DIFFERENT'}])
        get = api.get
        api.get = lambda path: (_ for _ in ()).throw(UniverseAPIError('Offline')) if '/changes/' in path else get(path)
        with self.assertRaises(UniverseAPIError):
            synchronize_universe(api=api)
        self.assertEqual(list(Part.objects.values()), before)
        self.assertEqual(UniverseSyncState.objects.values().get(pk=1), previous)
        with self.assertRaises(UniverseAPIError):
            self.sync([remote('NEW-001'), {**self.row, 'weight': '-2'}])
        self.assertEqual(list(Part.objects.values()), before)

    def test_policy_change_restarts_complete_download(self):
        api = FakeAPI([self.row])
        get = api.get
        api.get = Mock(side_effect=[ResyncRequired('Policy changed')])
        def changing(path):
            if not getattr(api, 'failed', False):
                api.failed = True
                raise ResyncRequired('Policy changed')
            return get(path)
        api.get = changing
        synchronize_universe(api=api)
        self.assertTrue(self.part.__class__.objects.get(pk=self.part.pk).catalog_available)

    def test_new_orders_use_central_client_and_explicit_sample_attribute(self):
        alias = Part.objects.create(number='MISSPELLED', client=self.client_record, sample_base=self.part)
        self.row['is_sample'] = True  # Catalog approval is independent of order sampling.
        self.sync()
        self.assertEqual(resolve_program_client(client_reference='CD0082', part_number=alias.number).name, self.row['customer'])
        order = create_program_order(client_name='Historical customer', client=self.client_record,
            part_number=alias.number, program='NEW', quantity=47)
        self.assertEqual(order.part_id, self.part.pk)
        self.assertEqual(order.quantity, 47)
        self.assertFalse(order.is_sample)
        sample = create_program_order(client_name='Historical customer', part_number=alias.number,
            program='NEW-SAMPLE', quantity=47, is_sample=True)
        self.assertTrue(sample.is_sample)
        self.assertEqual(sample.quantity, 5)
        with self.assertRaises(ValidationError):
            create_program_order(client_name='Central', part_number='UNKNOWN', program='INVALID', quantity=10)
        self.assertFalse(Part.objects.filter(number='UNKNOWN').exists())

    def test_local_catalog_mutations_are_blocked_and_view_uses_central_source(self):
        self.sync()
        user = get_user_model().objects.create_superuser('central-admin', password='test-password')
        self.client.force_login(user)
        response = self.client.get(reverse('universe'), {'catalog': 'all'})
        self.assertContains(response, 'Sincronizar ahora')
        self.assertContains(response, self.row['customer'])
        self.assertNotContains(response, 'Agregar pieza')
        self.assertNotContains(response, 'aria-label="Editar pieza')
        self.client.post(reverse('universe'), {'action': 'add', 'number': 'ILLEGAL', 'client': self.client_record.pk})
        self.assertFalse(Part.objects.filter(number='ILLEGAL').exists())
        self.assertEqual(self.client.post(reverse('edit-universe-part', args=[self.part.pk]), {'number': 'ILLEGAL'}).status_code, 302)
        self.assertFalse(Part.objects.filter(number='ILLEGAL').exists())
        old = Part.objects.create(number='OLD-UNAVAILABLE', catalog_available=False)
        order = ProductionOrder.objects.create(folio='HISTORY', program='OLD', part=old, quantity=5, remaining_quantity=5)
        form = ProductionOrderEditForm(instance=order)
        self.assertIn(old, form.fields['part'].queryset)
        for movement_form in (SurplusMovementForm(), ProcessMovementForm()):
            self.assertNotIn(old, movement_form.fields['part'].queryset)
            self.assertIn(self.part, movement_form.fields['part'].queryset)

    def test_central_rename_retains_id_and_old_input_alias(self):
        self.sync()
        self.row['part_number'] = 'CORRECTED-001'
        self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.number, 'CORRECTED-001')
        alias = Part.objects.get(number='CANONICAL-001')
        self.assertEqual(alias.sample_base_id, self.part.pk)
        order = create_program_order(client_name='ignored', part_number=alias.number, program='NEW', quantity=37)
        self.assertEqual(order.part_id, self.part.pk)
        self.assertFalse(order.is_sample)
        self.assertEqual(order.quantity, 37)

    def test_inactive_part_and_excluded_events_keep_history_but_block_new_orders(self):
        self.sync()
        event = {'part_id': self.row['id'], 'excluded': True, 'part': {'active': False}}
        synchronize_universe(api=FakeAPI([self.row], [event], policy=2, samples=False))
        self.part.refresh_from_db()
        self.assertFalse(self.part.catalog_available)
        self.assertIsNotNone(self.part.central_id)
        self.row['active'] = False
        self.assertEqual(self.sync()['available'], 0)
        self.assertEqual(Part.objects.count(), 1)

    def test_credentials_never_follow_cross_origin_urls(self):
        api = UniverseAPI()
        api.opener.open = Mock()
        with self.assertRaises(UniverseAPIError):
            api.get('https://another.example/api/v1/parts/')
        api.opener.open.assert_not_called()

    def test_conflicting_uuid_rolls_back_earlier_inserts_and_metadata_updates(self):
        self.sync()
        before = list(Part.objects.values())
        clients = list(Client.objects.values())
        # The first row can be applied, but the second must invalidate the whole batch.
        with self.assertRaises(UniverseAPIError):
            self.sync([remote('NEW-BEFORE-CONFLICT', customer='New customer'), remote(self.part.number)])
        self.assertEqual(list(Part.objects.values()), before)
        self.assertEqual(list(Client.objects.values()), clients)

    def test_sync_paginates_and_replays_tombstones(self):
        row2 = remote('SECOND')
        api = FakeAPI([self.row])
        get = api.get
        def paginated(path):
            if path == '/api/v1/parts/?page=2':
                return {'results': [row2], 'count': 2, 'next': None}
            if '/parts/?policy_version=' in path:
                return {'results': [self.row], 'count': 2, 'next': '/api/v1/parts/?page=2'}
            return get(path)
        api.get = paginated
        synchronize_universe(api=api)
        self.assertEqual(UniverseSyncState.objects.get(pk=1).part_count, 2)
        self.assertEqual(Part.objects.filter(catalog_available=True).count(), 2)
        self.assertEqual(synchronize_universe(api=api)['updated'], 0)

    @override_settings(UR_WEIGHT_UNIT='')
    def test_unspecified_weight_unit_preserves_operational_kg_and_keeps_raw_api_weight(self):
        self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.unit_weight_kg, Decimal('0.300000'))
        self.assertEqual(self.part.central_payload['weight'], self.row['weight'])
        self.row['weight'] = None
        self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.unit_weight_kg, Decimal('0.300000'))

    @override_settings(UR_WEIGHT_UNIT='g')
    def test_confirmed_grams_are_converted_to_operational_kg(self):
        self.row['weight'] = '125'
        self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.unit_weight_kg, Decimal('0.125000'))

    @override_settings(UR_WEIGHT_UNIT='kg')
    def test_piece_unit_from_universo_overrides_the_legacy_global_unit(self):
        self.row.update(weight='125', weight_unit='g')
        self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.unit_weight_kg, Decimal('0.125000'))
        self.assertEqual(self.part.central_payload['weight_unit'], 'g')

    @override_settings(UR_WEIGHT_UNIT='g')
    def test_piece_in_kilograms_is_not_converted_by_the_legacy_global_unit(self):
        self.row.update(weight='0.125', weight_unit='kg')
        self.sync()
        self.part.refresh_from_db()
        self.assertEqual(self.part.unit_weight_kg, Decimal('0.125'))

    @override_settings(UR_WEIGHT_UNIT='')
    def test_closing_requires_central_weight_and_per_piece_unit(self):
        self.part.central_payload = {'weight': '125', 'weight_unit': ''}
        self.part.save(update_fields=['central_payload'])
        UniverseSyncState.objects.create(enabled=True)
        order = ProductionOrder.objects.create(folio='WEIGHT-ORDER', program='S1', part=self.part,
                                               quantity=4, remaining_quantity=4)
        work = start_production(order=order, machine=Machine.objects.create(code='WEIGHT-MACHINE'), quantity=4)
        with self.assertRaisesMessage(ValidationError, 'confirma su unidad'):
            close_production(work_item=work, quantity=4)
        self.assertFalse(ProductionClose.objects.filter(work_item=work).exists())
        work.refresh_from_db()
        self.assertEqual(work.status, WorkInProcess.Status.ACTIVE)

    @override_settings(UR_WEIGHT_UNIT='')
    def test_old_api_without_unit_field_keeps_existing_closures_working(self):
        self.part.central_payload = {'weight': '0.300000'}
        self.part.save(update_fields=['central_payload'])
        UniverseSyncState.objects.create(enabled=True)
        order = ProductionOrder.objects.create(folio='LEGACY-WEIGHT-ORDER', program='S1', part=self.part,
                                               quantity=2, remaining_quantity=2)
        work = start_production(order=order, machine=Machine.objects.create(code='LEGACY-WEIGHT-MACHINE'), quantity=2)
        close = close_production(work_item=work, quantity=2)
        self.assertEqual(close.weight_kg, Decimal('0.600000'))

    @override_settings(UR_WEIGHT_UNIT='')
    def test_confirmed_central_grams_close_as_kilograms(self):
        self.part.central_payload = {'weight': '125', 'weight_unit': 'g'}
        self.part.unit_weight_kg = Decimal('0.125')
        self.part.save(update_fields=['central_payload', 'unit_weight_kg'])
        UniverseSyncState.objects.create(enabled=True)
        order = ProductionOrder.objects.create(folio='WEIGHT-ORDER', program='S1', part=self.part,
                                               quantity=4, remaining_quantity=4)
        work = start_production(order=order, machine=Machine.objects.create(code='WEIGHT-MACHINE'), quantity=4)
        close = close_production(work_item=work, quantity=4)
        self.assertEqual(close.weight_kg, Decimal('0.500'))
