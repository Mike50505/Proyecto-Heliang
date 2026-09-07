import hashlib
import json
from decimal import Decimal


def program_fingerprint(*, program, part_number, quantity, client_id=None,
                        line="", required_date=None, legacy=False):
    values = [program.strip(), part_number.strip(), format(Decimal(quantity).normalize(), "f")]
    if not legacy:
        values.extend([client_id, line.strip(), required_date.isoformat() if required_date else ""])
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()
