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

# Optional metadata (alliance / country) for the richer get_airline_info().
_AIRLINE_META: dict[str, dict] = {
    "AD": {"alliance": None, "country": "Brasil"},
    "G3": {"alliance": None, "country": "Brasil"},
    "LA": {"alliance": "oneworld", "country": "Chile"},
    "JJ": {"alliance": "oneworld", "country": "Brasil"},
    "TP": {"alliance": "Star Alliance", "country": "Portugal"},
    "AV": {"alliance": "Star Alliance", "country": "Colômbia"},
    "CM": {"alliance": "Star Alliance", "country": "Panamá"},
    "AA": {"alliance": "oneworld", "country": "EUA"},
    "DL": {"alliance": "SkyTeam", "country": "EUA"},
    "UA": {"alliance": "Star Alliance", "country": "EUA"},
    "IB": {"alliance": "oneworld", "country": "Espanha"},
    "AF": {"alliance": "SkyTeam", "country": "França"},
    "KL": {"alliance": "SkyTeam", "country": "Holanda"},
    "UX": {"alliance": "SkyTeam", "country": "Espanha"},
    "EK": {"alliance": None, "country": "Emirados Árabes"},
    "QR": {"alliance": "oneworld", "country": "Catar"},
    "BA": {"alliance": "oneworld", "country": "Reino Unido"},
    "AR": {"alliance": "SkyTeam", "country": "Argentina"},
}


def _code_for(raw: str) -> str | None:
    """Resolve an IATA code from a code or name, if possible."""
    up = (raw or "").strip().upper()
    if up in AIRLINES:
        return up
    low = (raw or "").strip().lower()
    full = _NAME_TO_FULL.get(low)
    if not full:
        for key, f in _NAME_TO_FULL.items():
            if key and key in low:
                full = f
                break
    if full:
        for code, name in AIRLINES.items():
            if name == full:
                return code
    return None


def logo_url_for(code: str | None) -> str:
    """CDN logo URL for an IATA code (avs.io). Empty string when unknown."""
    code = (code or "").strip().upper()
    if not code or code not in AIRLINES:
        return ""
    return f"https://pics.avs.io/200/80/{code}.png"


def get_airline_info(code_or_name: str | None) -> dict:
    """Return ``{"code", "name", "logo_url", "alliance", "country"}`` for an
    airline code or name. Unknown/empty inputs still return a safe dict with the
    full/cleaned name and an empty ``logo_url`` (the UI shows a plane fallback)."""
    name = get_airline_name(code_or_name)
    code = _code_for(code_or_name or "")
    meta = _AIRLINE_META.get(code or "", {})
    return {
        "code": code or "",
        "name": name,
        "logo_url": logo_url_for(code),
        "alliance": meta.get("alliance"),
        "country": meta.get("country"),
    }

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


__all__ = ["AIRLINES", "get_airline_name", "get_airline_info", "logo_url_for"]
