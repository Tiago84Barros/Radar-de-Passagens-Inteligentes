from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlparse


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_PRICE_RE = re.compile(r"R\$\s*([0-9.\s]+,\d{2})")
_DURATION_RE = re.compile(r"Dura[cç][aã]o:\s*([0-9]{1,2})h(?:\s*([0-9]{1,2})m)?", re.IGNORECASE)
_FLIGHT_RE = re.compile(r"\bVoo\s+([0-9A-Z]+)", re.IGNORECASE)


def parse_azul_visible_fares(
    visible_text: str,
    *,
    origin: str,
    destination: str,
    departure_date: date | str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Parse fares copied from Azul's visible results page.

    This is intentionally conservative: it only accepts rows where the pasted
    text has the requested origin/destination, a visible BRL price, and the URL
    belongs to Azul. It does not scrape hidden page state or infer missing fares.
    """
    source_url = _validated_azul_url(source_url)
    if not source_url:
        return []

    origin = (origin or "").upper().strip()
    destination = (destination or "").upper().strip()
    if not origin or not destination:
        return []

    day = _date_to_day(departure_date)
    lines = _clean_lines(visible_text)
    fares: list[dict[str, Any]] = []

    for index, line in enumerate(lines):
        if not _TIME_RE.match(line):
            continue
        if index + 1 >= len(lines) or lines[index + 1].upper() != origin:
            continue

        window = lines[index : index + 18]
        arrival_time = None
        for offset in range(2, min(len(window) - 1, 10)):
            if _TIME_RE.match(window[offset]) and window[offset + 1].upper() == destination:
                descriptor = " ".join(window[2:offset]).lower()
                if not any(marker in descriptor for marker in ("voo", "direto", "conex")):
                    continue
                arrival_time = window[offset]
                break
        if not arrival_time:
            continue

        price = _find_price(window)
        if not price:
            continue

        duration_minutes = _find_duration_minutes(window)
        flight_number = _find_flight_number(window)
        stops = _find_stops(window)
        fare = {
            "provider": "captura_assistida_azul",
            "source": "captura_assistida_azul",
            "source_name": "Azul",
            "source_url": source_url,
            "source_verified": True,
            "source_confidence": "verified",
            "origin": origin,
            "destination": destination,
            "departure_date": day,
            "departure_at": f"{day}T{_time_to_hhmm(line)}:00",
            "arrival_time": arrival_time,
            "airline": "Azul Linhas Aereas",
            "flight_number": flight_number or "",
            "price": price,
            "currency": "BRL",
            "duration_minutes": duration_minutes,
            "stops": stops,
            "booking_link": source_url,
            "raw_payload": {
                "capture_type": "visible_text",
                "source": "azul",
                "row_text": "\n".join(window),
            },
        }
        fares.append(fare)

    return _dedupe_fares(fares)


def _clean_lines(value: str) -> list[str]:
    return [
        line.strip()
        for line in str(value or "").replace("\xa0", " ").splitlines()
        if line.strip()
    ]


def _validated_azul_url(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    host = parsed.netloc.lower()
    if parsed.scheme != "https":
        return ""
    if host not in {"www.voeazul.com.br", "voeazul.com.br", "www.azul.com.br", "azul.com.br"}:
        return ""
    return text


def _find_price(lines: list[str]) -> float | None:
    for line in lines:
        match = _PRICE_RE.search(line)
        if match:
            return _parse_brl(match.group(1))
    return None


def _parse_brl(value: str) -> float | None:
    try:
        normalized = value.replace(" ", "").replace(".", "").replace(",", ".")
        return float(normalized)
    except (TypeError, ValueError):
        return None


def _find_duration_minutes(lines: list[str]) -> int | None:
    for line in lines:
        match = _DURATION_RE.search(line)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            return hours * 60 + minutes
    return None


def _find_flight_number(lines: list[str]) -> str | None:
    for line in lines:
        match = _FLIGHT_RE.search(line)
        if match:
            return match.group(1)
    return None


def _find_stops(lines: list[str]) -> int:
    text = " ".join(lines).lower()
    if "direto" in text:
        return 0
    match = re.search(r"(\d+)\s+conex", text)
    return int(match.group(1)) if match else 0


def _date_to_day(value: date | str) -> str:
    return value.isoformat()[:10] if hasattr(value, "isoformat") else str(value)[:10]


def _time_to_hhmm(value: str) -> str:
    hour, minute = value.split(":", 1)
    return f"{int(hour):02d}:{minute}"


def _dedupe_fares(fares: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fare in fares:
        key = (
            fare.get("origin"),
            fare.get("destination"),
            fare.get("departure_at"),
            fare.get("arrival_time"),
            fare.get("flight_number"),
            round(float(fare.get("price") or 0), 2),
        )
        unique.setdefault(key, fare)
    return sorted(unique.values(), key=lambda item: float(item.get("price") or 0))
