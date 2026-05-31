"""Airline catalog: map IATA codes (and short names) to full airline names.

Used wherever an airline is shown to the user (cards, tables, Telegram, history)
so the UI reads "GOL Linhas Aéreas" instead of "G3".
"""
from __future__ import annotations

# IATA code → full airline name.
AIRLINES: dict[str, str] = {
    "AD": "Azul Linhas Aéreas",
    "G3": "GOL Linhas Aéreas",
    "LA": "LATAM Airlines",
    "JJ": "LATAM Airlines Brasil",
    "TP": "TAP Air Portugal",
    "AA": "American Airlines",
    "DL": "Delta Air Lines",
    "UA": "United Airlines",
    "IB": "Iberia",
    "AF": "Air France",
    "KL": "KLM",
    "AV": "Avianca",
    "CM": "Copa Airlines",
    "AR": "Aerolíneas Argentinas",
    "EK": "Emirates",
    "QR": "Qatar Airways",
    "UX": "Air Europa",
    "LH": "Lufthansa",
    "BA": "British Airways",
    "AZ": "ITA Airways",
    "TK": "Turkish Airlines",
    "AC": "Air Canada",
}

# Lowercased short/common names → full name, so values already in short form
# ("LATAM", "GOL", "Azul", "TAP", "Aerolíneas") still resolve to the full label.
_SHORT_NAMES: dict[str, str] = {
    "latam": "LATAM Airlines",
    "gol": "GOL Linhas Aéreas",
    "azul": "Azul Linhas Aéreas",
    "tap": "TAP Air Portugal",
    "iberia": "Iberia",
    "avianca": "Avianca",
    "copa": "Copa Airlines",
    "delta": "Delta Air Lines",
    "united": "United Airlines",
    "american": "American Airlines",
    "emirates": "Emirates",
    "aerolíneas": "Aerolíneas Argentinas",
    "aerolineas": "Aerolíneas Argentinas",
    "lufthansa": "Lufthansa",
    "klm": "KLM",
    "air france": "Air France",
    "air europa": "Air Europa",
    "qatar": "Qatar Airways",
}

# Lowercased full name → itself (so an already-full value is recognised/kept).
_NAME_TO_FULL: dict[str, str] = {name.lower(): name for name in AIRLINES.values()}
_NAME_TO_FULL.update(_SHORT_NAMES)

_UNKNOWN = "Companhia não identificada"
_MISSING = "Companhia não informada"


def get_airline_name(code_or_name: str | None) -> str:
    """Return the full airline name for an IATA code or (short/full) name.

    - Known IATA code  → full name ("G3" → "GOL Linhas Aéreas").
    - Known name       → full name ("LATAM" → "LATAM Airlines").
    - Combined/hub legs ("LA + TP", "via GRU") → kept as-is.
    - Empty            → "Companhia não informada".
    - Anything else    → the original value, cleaned (never a bare code dump).
    """
    raw = (code_or_name or "").strip()
    if not raw:
        return _MISSING
    if raw.lower() in {"não informada", "nao informada", "não informado", "nao informado"}:
        return _MISSING

    # Combined itineraries / hub connections: keep the human-readable composition.
    if "+" in raw or " via " in f" {raw.lower()} ":
        return raw

    up = raw.upper()
    if up in AIRLINES:
        return AIRLINES[up]

    low = raw.lower()
    if low in _NAME_TO_FULL:
        return _NAME_TO_FULL[low]

    # Partial match (e.g. "GOL Linhas Aéreas SA" contains "gol").
    for key, full in _NAME_TO_FULL.items():
        if key in low:
            return full

    # A lone 2-letter unknown code is not user-friendly; otherwise keep the value.
    if len(raw) <= 2 and raw.isalnum():
        return _UNKNOWN
    return raw


__all__ = ["AIRLINES", "get_airline_name"]
