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
    "quote_age_hours",
    "format_collected_age",
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


def quote_age_hours(collected_at) -> float | None:
    """Age of a quote, in hours, based on when it was collected.

    Returns None when the timestamp is missing/unparseable. Airfares expire fast,
    so callers use this to flag or hide stale snapshots."""
    if collected_at is None:
        return None
    import pandas as pd

    ts = pd.to_datetime(collected_at, errors="coerce", utc=True)
    if ts is None or pd.isna(ts):
        return None
    delta = pd.Timestamp.now(tz="UTC") - ts
    hours = delta.total_seconds() / 3600.0
    return hours if hours >= 0 else 0.0


def format_collected_age(collected_at) -> str:
    """Human 'collected ago' label: 'agora há pouco', 'há 2 h', 'há 3 dias'.

    Returns '' when the timestamp is missing so callers can omit the chip."""
    hours = quote_age_hours(collected_at)
    if hours is None:
        return ""
    minutes = hours * 60
    if minutes < 5:
        return "agora há pouco"
    if minutes < 60:
        return f"há {int(round(minutes))} min"
    if hours < 24:
        return f"há {int(round(hours))} h"
    days = int(hours // 24)
    return "há 1 dia" if days == 1 else f"há {days} dias"
