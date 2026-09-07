import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from operations.models import Client, Part


def text(value):
    return "" if value is None else str(value).strip()


def client_code(name):
    return re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:30]


class Command(BaseCommand):
    help = "Importa la relación cliente/número de parte desde Universo Ramos."

    def add_arguments(self, parser):
        parser.add_argument("workbook", type=Path)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula la importación y revierte todos los cambios al terminar.",
        )
        parser.add_argument(
            "--overwrite-diameters",
            action="store_true",
            help="Reemplaza diámetros existentes. Por omisión solo completa campos vacíos.",
        )
        parser.add_argument(
            "--diameters-only",
            action="store_true",
            help="Carga solamente diámetros, sin modificar clientes ni sus identificadores.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        source = options["workbook"]
        if not source.exists():
            raise CommandError(f"No existe {source}")

        workbook = load_workbook(source, data_only=True, read_only=True)
        sheet_name = "Sheet1 (2)" if "Sheet1 (2)" in workbook.sheetnames else "Sheet1"
        sheet = workbook[sheet_name]
        has_external_id = sheet_name == "Sheet1 (2)"
        overwrite_diameters = options["overwrite_diameters"]
        diameters_only = options["diameters_only"]
        updated_parts = 0
        missing_parts = 0
        diameters_added = 0
        diameters_overwritten = 0
        diameter_conflicts = 0
        clients_seen = set()

        # Un mismo número puede aparecer varias veces en el libro. Si sus textos
        # de diámetro no coinciden, no elegimos uno arbitrariamente.
        diameter_values = {}
        for row in sheet.iter_rows(min_row=2, values_only=True):
            part_index = 4 if has_external_id else 3
            diameter_index = 5 if has_external_id else 4
            part_number = text(row[part_index] if len(row) > part_index else "")
            diameter = text(row[diameter_index] if len(row) > diameter_index else "")
            if (part_number and part_number.upper() != "NÚMERO DE PARTE"
                    and diameter and diameter.upper() != "DIAMETRO"):
                diameter_values.setdefault(part_number, set()).add(diameter)
        conflicting_parts = {
            part_number for part_number, values in diameter_values.items() if len(values) > 1
        }

        for row in sheet.iter_rows(min_row=2, values_only=True):
            name = text(row[1] if len(row) > 1 else "")
            external_id = text(row[2] if has_external_id and len(row) > 2 else "")
            part_index = 4 if has_external_id else 3
            diameter_index = 5 if has_external_id else 4
            part_number = text(row[part_index] if len(row) > part_index else "")
            diameter = text(row[diameter_index] if len(row) > diameter_index else "")
            if not name or name.upper() == "CLIENTE" or not part_number or part_number.upper() == "NÚMERO DE PARTE":
                continue

            client = None
            if not diameters_only:
                if external_id.upper() in {"#N/A", "N/A", "NA"}:
                    external_id = ""
                code = client_code(name)
                client, _ = Client.objects.get_or_create(code=code, defaults={"name": name})
                changed = []
                if client.name != name:
                    client.name = name
                    changed.append("name")
                if client.external_id != external_id:
                    client.external_id = external_id
                    changed.append("external_id")
                if changed:
                    changed.append("updated_at")
                    client.save(update_fields=changed)
                clients_seen.add(client.pk)

            part = Part.objects.filter(number=part_number).first()
            if part is None:
                missing_parts += 1
                continue
            part_changes = []
            if client is not None and part.client_id != client.pk:
                part.client = client
                part_changes.append("client")
            if diameter and part_number not in conflicting_parts:
                if not part.diameter:
                    part.diameter = diameter
                    part_changes.append("diameter")
                    diameters_added += 1
                elif overwrite_diameters and part.diameter != diameter:
                    part.diameter = diameter
                    part_changes.append("diameter")
                    diameters_overwritten += 1
            if part_changes:
                part.save(update_fields=[*part_changes, "updated_at"])
            updated_parts += 1

        diameter_conflicts = len(conflicting_parts)

        self.stdout.write(self.style.SUCCESS("Relación de clientes importada"))
        self.stdout.write(f"  clientes: {len(clients_seen)}")
        self.stdout.write(f"  números de parte relacionados: {updated_parts}")
        self.stdout.write(f"  números de parte no encontrados: {missing_parts}")
        self.stdout.write(f"  diámetros agregados: {diameters_added}")
        self.stdout.write(f"  diámetros sobrescritos: {diameters_overwritten}")
        self.stdout.write(f"  diámetros omitidos por conflicto: {diameter_conflicts}")
        for part_number in sorted(conflicting_parts):
            values = ", ".join(sorted(diameter_values[part_number]))
            self.stdout.write(self.style.WARNING(
                f"    {part_number}: {values}"
            ))
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING(
                "  simulación: todos los cambios fueron revertidos"
            ))
