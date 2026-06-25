from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote_plus, urlencode


def build_official_search_links(form: dict[str, Any]) -> list[dict[str, str]]:
    origin = str(form.get("origin_iata") or form.get("origin") or "").upper().strip()
    destination = str(form.get("destination_iata") or form.get("destination") or "").upper().strip()
    departure = _parse_day(form.get("departure_date"))
    return_day = _parse_day(form.get("return_date"))
    adults = _positive_int(form.get("adults") or form.get("passengers"), default=1)

    if not origin or not destination or departure is None:
        return []

    links = [
        {
            "label": "Azul",
            "url": _azul_search_url(origin, destination, departure, return_day, adults),
            "kind": "official_airline",
        },
        {
            "label": "Google Flights",
            "url": _google_flights_url(origin, destination, departure, return_day, adults),
            "kind": "metasearch",
        },
        {
            "label": "Skyscanner",
            "url": _skyscanner_url(origin, destination, departure, return_day, adults),
            "kind": "metasearch",
        },
        {
            "label": "Kayak",
            "url": _kayak_url(origin, destination, departure, return_day, adults),
            "kind": "metasearch",
        },
    ]
    return links


def _azul_search_url(origin: str, destination: str, departure: date, return_day: date | None, adults: int) -> str:
    params: list[tuple[str, str]] = [
        ("c[0].ds", origin),
        ("c[0].std", departure.strftime("%m/%d/%Y")),
        ("c[0].as", destination),
    ]
    if return_day:
        params.extend(
            [
                ("c[1].ds", destination),
                ("c[1].std", return_day.strftime("%m/%d/%Y")),
                ("c[1].as", origin),
            ]
        )
    params.extend(
        [
            ("p[0].t", "ADT"),
            ("p[0].c", str(adults)),
            ("p[0].cp", "false"),
            ("f.dl", "3"),
            ("f.dr", "3"),
            ("cc", "BRL"),
        ]
    )
    return "https://www.voeazul.com.br/br/pt/home/selecao-voo?" + urlencode(params, safe="[]")


def _google_flights_url(origin: str, destination: str, departure: date, return_day: date | None, adults: int) -> str:
    query = f"voos {origin} para {destination} ida {departure.isoformat()}"
    if return_day:
        query += f" volta {return_day.isoformat()}"
    query += f" {adults} adulto"
    if adults > 1:
        query += "s"
    return "https://www.google.com/travel/flights?q=" + quote_plus(query)


def _skyscanner_url(origin: str, destination: str, departure: date, return_day: date | None, adults: int) -> str:
    dep = departure.strftime("%y%m%d")
    ret = return_day.strftime("%y%m%d") if return_day else ""
    route = f"{origin.lower()}/{destination.lower()}/{dep}/"
    if ret:
        route += f"{ret}/"
    query = urlencode({"adultsv2": adults, "cabinclass": "economy", "currency": "BRL"})
    return f"https://www.skyscanner.com.br/transport/flights/{route}?{query}"


def _kayak_url(origin: str, destination: str, departure: date, return_day: date | None, adults: int) -> str:
    path = f"{origin}-{destination}/{departure.isoformat()}"
    if return_day:
        path += f"/{return_day.isoformat()}"
    path += f"/{adults}adults"
    return f"https://www.kayak.com.br/flights/{path}?sort=bestflight_a"


def _parse_day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
