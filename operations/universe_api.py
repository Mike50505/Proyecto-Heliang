"""Transactional read cache of Universo Ramos. Production rows are never rewritten."""
import hashlib
import json
import unicodedata
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urljoin, urlsplit
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Client, Part, UniverseSyncState


class UniverseAPIError(Exception):
    pass


class ResyncRequired(UniverseAPIError):
    pass


def central_catalog_enabled():
    return UniverseSyncState.objects.filter(pk=1, enabled=True).exists()


def require_local_catalog():
    if central_catalog_enabled():
        raise ValidationError('El catálogo se administra en Universo Ramos. Actualiza la pieza en esa aplicación.')


def normalize_code(value):
    return unicodedata.normalize('NFKC', value).strip().upper()


class UniverseAPI:
    def __init__(self):
        self.base = settings.UR_BASE_URL.rstrip('/')
        self.token = settings.UR_API_KEY
        parsed = urlsplit(self.base)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise UniverseAPIError('Configura una URL HTTPS válida para Universo Ramos.')
        if not self.token:
            raise UniverseAPIError('Falta configurar la clave de Universo Ramos en el servidor.')
        base = self.base

        class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, message, headers, url):
                if urlsplit(url)[:2] != urlsplit(base)[:2]:
                    raise UniverseAPIError('La API intentó redirigir a otro servidor.')
                return super().redirect_request(request, fp, code, message, headers, url)

        self.opener = urllib.request.build_opener(SameOriginRedirect())

    def get(self, path):
        url = urljoin(self.base + '/', path)
        parsed = urlsplit(url)
        if parsed[:2] != urlsplit(self.base)[:2] or parsed.username or parsed.password:
            raise UniverseAPIError('La API devolvió un enlace a otro servidor.')
        request = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
            'User-Agent': 'Heiliang-Catalog-Verification/1.0', 'Cache-Control': 'no-cache'})
        try:
            with self.opener.open(request, timeout=settings.UR_REQUEST_TIMEOUT_SECONDS) as response:
                data = json.load(response)
            if not isinstance(data, dict):
                raise UniverseAPIError('Respuesta inválida de Universo Ramos.')
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise ResyncRequired('Cambió el permiso del catálogo.') from None
            raise UniverseAPIError(f'Universo Ramos respondió HTTP {exc.code}. Se conserva la última sincronización.') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise UniverseAPIError('No se pudo consultar Universo Ramos. Se conserva la última sincronización.') from None


def download_catalog(api):
    bootstrap = api.get('/api/v1/bootstrap/')
    url = bootstrap['parts_url']
    url += ('&' if '?' in url else '?') + 'page_size=200'
    parts, visited = {}, set()
    while url:
        if url in visited:
            raise UniverseAPIError('La API repitió una página del catálogo.')
        visited.add(url)
        page = api.get(url)
        for part in page['results']:
            key = str(UUID(str(part['id'])))
            if key in parts:
                raise UniverseAPIError('El catálogo cambió durante la descarga; vuelve a sincronizar.')
            parts[key] = part
        url = page['next']
    # Replay from the bootstrap cursor to close gaps from concurrent imports.
    cursor, seen_cursors = bootstrap['changes_cursor'], set()
    while True:
        if cursor in seen_cursors:
            raise UniverseAPIError('La API repitió un cursor de cambios.')
        seen_cursors.add(cursor)
        page = api.get('/api/v1/changes/?limit=200&cursor=' + quote(cursor, safe=''))
        for event in page['results']:
            key = str(UUID(str(event['part_id'])))
            if event.get('excluded', False):
                parts.pop(key, None)
            else:
                parts[key] = {**event['part'], 'id': key}
        cursor = page['next_cursor']
        if not page['has_more']:
            break
    catalogs = api.get('/api/v1/catalogs/')
    maps = {field: {str(row['id']): row['name'] for row in catalogs[key]}
            for field, key in (('customer', 'customers'), ('destination', 'destinations'),
                               ('box', 'boxes'), ('sheet_color', 'sheet_colors'))}
    for key, part in list(parts.items()):
        # Change events have catalog UUIDs; list responses have readable names.
        missing = False
        for field, names in maps.items():
            if field + '_id' in part:
                value = part[field + '_id']
                if value is not None and str(value) not in names:
                    missing = True
                part[field] = names.get(str(value)) if value is not None else None
        if missing:
            parts[key] = api.get(f'/api/v1/parts/{key}/')
    if api.get('/api/v1/bootstrap/')['policy_version'] != bootstrap['policy_version']:
        raise ResyncRequired('Cambió el permiso durante la descarga.')
    return parts, bootstrap, cursor


def catalog_snapshot(part):
    return {'number': part.number, 'client_id': part.client_id, 'diameter': part.diameter,
            'unit_weight_kg': str(part.unit_weight_kg) if part.unit_weight_kg is not None else None,
            'in_universe_ramos': part.in_universe_ramos,
            'universe_added_at': part.universe_added_at.isoformat() if part.universe_added_at else None}


def validate_parts(parts, include_samples):
    numbers = set()
    for part in parts.values():
        number = part['part_number']
        customer = part['customer']
        if not isinstance(number, str) or not number.strip() or len(number) > 120:
            raise UniverseAPIError('La API devolvió un número de parte inválido.')
        code = normalize_code(number)
        if code in numbers or code == 'TOTALES':
            raise UniverseAPIError('La API contiene un número repetido o reservado.')
        numbers.add(code)
        if not isinstance(customer, str) or not customer.strip() or len(customer) > 150:
            raise UniverseAPIError('La API devolvió un cliente inválido.')
        if not isinstance(part.get('diameter', ''), str) or len(part.get('diameter', '')) > 120:
            raise UniverseAPIError('La API devolvió un diámetro inválido.')
        if type(part.get('active')) is not bool or type(part.get('is_sample', False)) is not bool:
            raise UniverseAPIError('La API devolvió una disponibilidad inválida.')
        if not include_samples and part.get('is_sample', False):
            raise ResyncRequired('Cambió el permiso de pendientes de aprobación.')
        weight = part.get('weight')
        weight_unit = part.get('weight_unit')
        if 'weight_unit' in part and weight_unit not in ('', 'kg', 'g'):
            raise UniverseAPIError('La API devolvió una unidad de peso inválida.')
        if weight is not None:
            try:
                value = Decimal(str(weight))
                Part._meta.get_field('unit_weight_kg').clean(value, None)
            except (InvalidOperation, ValidationError, ValueError):
                raise UniverseAPIError('La API devolvió un peso inválido.') from None


def apply_catalog(parts, bootstrap, cursor, state, user=None):
    validate_parts(parts, bootstrap['include_samples'])
    local = list(Part.objects.select_for_update().filter(sample_base__isnull=True))
    by_code, by_id = {}, {}
    for part in local:
        code = normalize_code(part.number)
        if code in by_code:
            raise UniverseAPIError('Hay números locales ambiguos. Revisa el catálogo antes de sincronizar.')
        by_code[code] = part
        if part.central_id:
            by_id[str(part.central_id)] = part
    now = timezone.now()
    linked_ids, created, changed = [], 0, 0
    client_cache = {}
    for key, payload in parts.items():
        code = normalize_code(payload['part_number'])
        part = by_id.get(key) or by_code.get(code)
        if part and part.central_id and str(part.central_id) != key:
            raise UniverseAPIError('Un código local ya está vinculado a otro UUID central.')
        if part and by_code.get(code) not in (None, part):
            raise UniverseAPIError('El cambio de número central coincide con otra pieza local. Revisa la equivalencia.')
        name = payload['customer'].strip()
        if name not in client_cache:
            client = Client.objects.filter(name__iexact=name).order_by('pk').first()
            if client is None:
                client = Client.objects.create(code='UR-' + hashlib.sha256(name.casefold().encode()).hexdigest()[:24], name=name)
            client_cache[name] = client
        client = client_cache[name]
        available = payload['active']
        weight = Decimal(str(payload['weight'])) if payload.get('weight') is not None else None
        # New Universo Ramos responses declare the unit for each part. Older
        # responses can still use the explicitly configured legacy unit.
        weight_unit = payload.get('weight_unit') if 'weight_unit' in payload else settings.UR_WEIGHT_UNIT
        if weight_unit == 'g' and weight is not None:
            weight = (weight / Decimal('1000')).quantize(Decimal('0.000001'))
        elif weight_unit not in ('kg', 'g'):
            # The API explicitly does not infer weight units. Keep raw weight in
            # central_payload; never treat an unconfirmed unit as kilograms.
            if part and part.local_catalog_snapshot:
                previous = part.local_catalog_snapshot.get('unit_weight_kg')
                weight = Decimal(previous) if previous is not None else None
            else:
                weight = part.unit_weight_kg if part else None
        if part is None:
            # Do not recreate a historical alias under a new central UUID.
            if Part.objects.filter(number=code).exists():
                raise UniverseAPIError('Un número central coincide con un alias histórico. Revisa la equivalencia.')
            part = Part.objects.create(number=code, client=client, diameter=payload.get('diameter', ''),
                unit_weight_kg=weight, in_universe_ramos=available, universe_added_at=now,
                central_id=key, central_payload=payload, catalog_available=available)
            created += 1
        else:
            snapshot = part.local_catalog_snapshot
            if not snapshot and not part.central_id:
                snapshot = catalog_snapshot(part)
            if part.number != code:
                # Preserve old spellings as input aliases without moving any order.
                if not Part.objects.filter(number=part.number).exclude(pk=part.pk).exists():
                    old_number = part.number
                    # Rename first to free the unique number for its historical alias.
                    Part.objects.filter(pk=part.pk).update(number=code)
                    Part.objects.create(number=old_number, client_id=part.client_id,
                        diameter=part.diameter, unit_weight_kg=part.unit_weight_kg,
                        sample_base=part, catalog_available=False)
            fields = dict(number=code, client_id=client.pk, diameter=payload.get('diameter', ''),
                unit_weight_kg=weight, central_id=UUID(key), central_payload=payload,
                local_catalog_snapshot=snapshot, catalog_available=available, in_universe_ramos=available)
            if any(getattr(part, field) != value for field, value in fields.items()):
                Part.objects.filter(pk=part.pk).update(**fields)
                changed += 1
        linked_ids.append(part.pk)
    # Withdraw obsolete/unauthorized entries from new captures, never from history.
    Part.objects.exclude(pk__in=linked_ids).update(in_universe_ramos=False, catalog_available=False)
    state.enabled = True
    state.source_url = settings.UR_BASE_URL.rstrip('/')
    state.credential_fingerprint = hashlib.sha256(settings.UR_API_KEY.encode()).hexdigest()
    state.cursor = cursor
    state.policy_version = bootstrap['policy_version']
    state.include_samples = bootstrap['include_samples']
    state.last_success_at = now
    state.last_error = ''
    state.part_count = sum(part['active'] for part in parts.values())
    state.save()
    if created or changed:
        AuditEvent.objects.create(user=user, action='SYNC_UNIVERSE_RAMOS', entity='Part',
            data={'source': state.source_url, 'created': created, 'updated': changed,
                  'available': state.part_count, 'policy_version': state.policy_version})
    return {'created': created, 'updated': changed, 'available': state.part_count}


def synchronize_universe(*, api=None, user=None):
    api = api or UniverseAPI()
    for attempt in range(3):
        try:
            with transaction.atomic():
                state, _ = UniverseSyncState.objects.get_or_create(pk=1)
                state = UniverseSyncState.objects.select_for_update().get(pk=state.pk)
                if state.enabled and state.source_url != settings.UR_BASE_URL.rstrip('/'):
                    raise UniverseAPIError('La URL configurada no coincide con el catálogo vinculado.')
                parts, bootstrap, cursor = download_catalog(api)
                return apply_catalog(parts, bootstrap, cursor, state, user=user)
        except ResyncRequired:
            if attempt == 2:
                raise
