from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import gcd
import re


def format_diameter_fraction(value):
    """Render a numeric diameter as the nearest sixteenth of an inch."""
    if value is None:
        return ""

    text = str(value).strip()
    if not text or "/" in text:
        return text

    try:
        diameter = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return text

    if not diameter.is_finite() or diameter < 0:
        return text

    sixteenths = int((diameter * 16).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    whole, numerator = divmod(sixteenths, 16)
    if numerator == 0:
        return str(whole)

    divisor = gcd(numerator, 16)
    fraction = f"{numerator // divisor}/{16 // divisor}"
    return f"{whole} {fraction}" if whole else fraction


_FRACTION_PATTERN = re.compile(r"(?<!\d)(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)(?!\d)")


def diameter_category(value):
    """Return the measurement portion used to group Heliang priorities."""
    formatted = format_diameter_fraction(value)
    match = _FRACTION_PATTERN.search(formatted)
    if not match:
        return formatted or "Sin diámetro"

    whole, numerator, denominator = match.groups()
    fraction = f"{int(numerator)}/{int(denominator)}"
    return f"{int(whole)} {fraction}" if whole else fraction


def diameter_category_sort_key(category):
    match = _FRACTION_PATTERN.fullmatch(category)
    if not match:
        return (1, category.casefold())
    whole, numerator, denominator = match.groups()
    numeric = Decimal(int(whole or 0)) + (Decimal(int(numerator)) / Decimal(int(denominator)))
    return (0, numeric)
