from __future__ import annotations

from datetime import date, datetime

from app.formatting import format_brl
from services.miles_service import estimate_miles, format_miles

__all__ = [
    "format_brl",
    "format_miles",
    "estimate_miles",
    "format_date_br",
    "format_duration_short",
    "format_stops",
]


def format_date_br(value) -> str:
    """Format a date as dd/mm/aaaa. Returns '—' when missing/unparseable."""
    if value is None:
        return "—"
    if isinstance(value, (datetime, date)):
        return value.strftime("%d/%m/%Y")
    try:
        import pandas as pd

        parsed = pd.to_datetime(value, errors="coerce")
        if parsed is None or pd.isna(parsed):
            return "—"
        return parsed.strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def format_duration_short(minutes) -> str:
    """Format total travel time as '13h40' (or '45min' under an hour)."""
    try:
        total = int(float(minutes))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    h, m = divmod(total, 60)
    if h and m:
        return f"{h}h{m:02d}"
    if h:
        return f"{h}h"
    return f"{m}min"


def format_stops(stops) -> str:
    """Human label for number of stops: 'direto', '1 conexão', '2 conexões'."""
    try:
        n = int(float(stops))
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return "direto"
    if n == 1:
        return "1 conexão"
    return f"{n} conexões"
