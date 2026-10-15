from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client as WebClient
from django.urls import reverse
from django.utils import timezone

from operations.models import AuditEvent, Client, Part, ProductionOrder

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog():
    user = get_user_model().objects.create_user('piece-editor')
    access = user.module_access
    access.universe = access.universe_edit = True
    access.save()
    customer = Client.objects.create(code='EDIT', name='Cliente original')
    part = Part.objects.create(number='EDIT-PART', client=customer, diameter='1/2',
                               unit_weight_kg=Decimal('0.25'), in_universe_ramos=True,
                               universe_added_at=timezone.now())
    web = WebClient()
    web.force_login(user)
    return user, part, web


def payload(part, **changes):
    return {'number': part.number, 'client': part.client_id or '', 'diameter': part.diameter,
            'unit_weight_kg': str(part.unit_weight_kg or ''), **changes}


def test_edits_catalog_preserving_identity_membership_date_and_order(catalog):
    user, part, web = catalog
    order = ProductionOrder.objects.create(folio='EDIT-ORDER', program='S41', part=part,
                                            quantity=5, remaining_quantity=5)
    date = part.universe_added_at
    customer = Client.objects.create(code='NEW', name='Nuevo cliente')
    url = reverse('edit-universe-part', args=[part.pk]) + '?catalog=all&client=Original'
    response = web.get(url)
    assert response.status_code == 200
    assert 'EDIT-PART' in response.content.decode()
    response = web.post(url, payload(part, number='CORRECTED', client=customer.pk,
                                     diameter='3/8', unit_weight_kg='0.123456'))
    assert response.status_code == 302
    assert response['Location'] == reverse('universe') + '?catalog=all&client=Original'
    part.refresh_from_db()
    order.refresh_from_db()
    assert part.number == 'CORRECTED'
    assert part.client == customer
    assert part.diameter == '3/8'
    assert part.unit_weight_kg == Decimal('0.123456')
    assert part.in_universe_ramos
    assert part.universe_added_at == date
    assert order.part_id == part.pk
    event = AuditEvent.objects.get(action='EDIT_UNIVERSE_PART')
    assert event.user == user
    assert event.data['before']['number'] == 'EDIT-PART'
    assert event.data['after']['client_id'] == customer.pk


@pytest.mark.parametrize('permission', ['universe', 'universe_edit'])
def test_permissions_are_enforced_for_direct_get_and_post(catalog, permission):
    user, part, web = catalog
    access = user.module_access
    setattr(access, permission, False)
    access.save()
    url = reverse('edit-universe-part', args=[part.pk])
    assert web.get(url).status_code == 302
    assert web.post(url, payload(part, number='UNAUTHORIZED')).status_code == 302
    part.refresh_from_db()
    assert part.number == 'EDIT-PART'
    assert not AuditEvent.objects.filter(action='EDIT_UNIVERSE_PART').exists()
    if permission == 'universe_edit':
        assert url.encode() not in web.get(reverse('universe')).content


def test_table_has_edit_link_and_preserves_filters(catalog):
    user, part, web = catalog
    response = web.get(reverse('universe'), {'catalog': 'all', 'q': 'EDIT-PART'})
    assert response.status_code == 200
    assert reverse('edit-universe-part', args=[part.pk]).encode() in response.content
    assert b'catalog=all&amp;q=EDIT-PART' in response.content


def test_duplicate_number_is_rejected_without_partial_changes(catalog):
    user, part, web = catalog
    Part.objects.create(number='OTHER')
    response = web.post(reverse('edit-universe-part', args=[part.pk]),
                        payload(part, number='other', diameter='7/8'))
    assert response.status_code == 200
    assert 'ya está registrado' in response.content.decode()
    part.refresh_from_db()
    assert part.number == 'EDIT-PART' and part.diameter == '1/2'
    assert not AuditEvent.objects.filter(action='EDIT_UNIVERSE_PART').exists()


def test_editing_outside_universe_preserves_membership_and_zero_weight(catalog):
    user, part, web = catalog
    part.in_universe_ramos = False
    part.universe_added_at = None
    part.save()
    response = web.post(reverse('edit-universe-part', args=[part.pk]),
                        payload(part, unit_weight_kg='0', client=''))
    assert response.status_code == 302
    part.refresh_from_db()
    assert not part.in_universe_ramos and part.universe_added_at is None
    assert part.unit_weight_kg == 0 and part.client is None


def test_negative_weight_is_rejected(catalog):
    user, part, web = catalog
    response = web.post(reverse('edit-universe-part', args=[part.pk]),
                        payload(part, unit_weight_kg='-1'))
    assert response.status_code == 200
    part.refresh_from_db()
    assert part.unit_weight_kg == Decimal('0.25')


def test_get_and_csrf_failure_leave_catalog_unchanged(catalog):
    user, part, web = catalog
    url = reverse('edit-universe-part', args=[part.pk])
    assert web.get(url).status_code == 200
    assert not AuditEvent.objects.filter(action='EDIT_UNIVERSE_PART').exists()
    secure = WebClient(enforce_csrf_checks=True)
    secure.force_login(user)
    assert secure.post(url, payload(part, number='INVALID')).status_code == 403
    part.refresh_from_db()
    assert part.number == 'EDIT-PART'


def test_legacy_edit_uses_same_validation_and_audit(catalog):
    user, part, web = catalog
    response = web.post(reverse('universe'),
                        payload(part, action='edit', part_id=part.pk, diameter='3/4'))
    assert response.status_code == 302
    part.refresh_from_db()
    assert part.diameter == '3/4'
    assert AuditEvent.objects.filter(action='EDIT_UNIVERSE_PART').count() == 1
