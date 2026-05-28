from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def is_iata_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", str(value or "").upper()))


def validate_search_params(params: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not is_iata_code(str(params.get("origin", ""))):
        errors.append("Origem deve resolver para um codigo IATA de 3 letras.")
    if not is_iata_code(str(params.get("destination", ""))):
        errors.append("Destino deve resolver para um codigo IATA de 3 letras.")
    if not _valid_date(params.get("departure_date")):
        errors.append("Data de ida invalida.")
    return_date = params.get("return_date")
    if return_date and not _valid_date(return_date):
        errors.append("Data de volta invalida.")
    return errors


def _valid_date(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    try:
        datetime.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return False
    return True
