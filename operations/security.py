from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError


MAX_XLSX_ROWS = 5000
MAX_XLSX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_XLSX_ENTRY = 20 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def validate_xlsx_archive(upload):
    """Reject oversized or suspicious OOXML ZIP containers before parsing."""
    upload.seek(0)
    try:
        with ZipFile(upload) as archive:
            total = 0
            for entry in archive.infolist():
                total += entry.file_size
                if entry.file_size > MAX_XLSX_ENTRY or total > MAX_XLSX_UNCOMPRESSED:
                    raise ValidationError("El contenido descomprimido del Excel es demasiado grande.")
                if entry.file_size and entry.compress_size == 0:
                    raise ValidationError("El archivo Excel tiene una entrada comprimida inválida.")
                if entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
                    raise ValidationError("El archivo Excel tiene una compresión anormal.")
    except BadZipFile as exc:
        raise ValidationError("El archivo no es un Excel válido.") from exc
    finally:
        upload.seek(0)


def spreadsheet_safe(value):
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return value
