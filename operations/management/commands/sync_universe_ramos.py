import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from operations.models import UniverseSyncState
from operations.universe_api import UniverseAPIError, synchronize_universe


class Command(BaseCommand):
    help = 'Sincroniza el catálogo desde Universo Ramos sin alterar producción histórica.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true', help='Mantener sincronización automática.')
        parser.add_argument('--interval', type=int, default=300)

    def handle(self, *args, **options):
        if options['interval'] < 30:
            raise CommandError('El intervalo mínimo es de 30 segundos.')
        while True:
            try:
                result = synchronize_universe()
                self.stdout.write(self.style.SUCCESS(
                    f"Universo Ramos: {result['available']} disponibles, {result['created']} nuevas, {result['updated']} actualizadas."))
                self.stdout.flush()
            except (UniverseAPIError, KeyError, TypeError, ValueError) as exc:
                # No response bodies, URLs with credentials, or request headers in logs.
                message = str(exc) if isinstance(exc, UniverseAPIError) else 'Respuesta inválida de Universo Ramos. Se conserva el catálogo anterior.'
                UniverseSyncState.objects.filter(pk=1).update(last_error=message[:240])
                if not options['watch']:
                    raise CommandError(message) from None
                self.stderr.write(message)
            if not options['watch']:
                break
            close_old_connections()
            time.sleep(options['interval'])
