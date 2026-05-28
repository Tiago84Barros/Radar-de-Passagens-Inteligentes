from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import requests


AUTOCOMPLETE_URL = "https://autocomplete.travelpayouts.com/places2"

COUNTRY_MAIN_CODES = {
    "BR": "GRU",
    "BRAZIL": "GRU",
    "BRASIL": "GRU",
    "PT": "LIS",
    "PORTUGAL": "LIS",
    "US": "NYC",
    "USA": "NYC",
    "UNITED STATES": "NYC",
    "ESTADOS UNIDOS": "NYC",
    "FR": "PAR",
    "FRANCE": "PAR",
    "FRANCA": "PAR",
    "FRANÇA": "PAR",
    "ES": "MAD",
    "SPAIN": "MAD",
    "ESPANHA": "MAD",
    "IT": "ROM",
    "ITALY": "ROM",
    "ITALIA": "ROM",
    "ITÁLIA": "ROM",
    "GB": "LON",
    "UK": "LON",
    "UNITED KINGDOM": "LON",
    "REINO UNIDO": "LON",
    "DE": "BER",
    "GERMANY": "BER",
    "ALEMANHA": "BER",
    "AR": "BUE",
    "ARGENTINA": "BUE",
    "CL": "SCL",
    "CHILE": "SCL",
    "UY": "MVD",
    "URUGUAY": "MVD",
}


@dataclass(frozen=True)
class LocationResolution:
    original: str
    code: str
    label: str
    source: str
    location_type: str = "iata"


def resolve_location(value: str) -> LocationResolution | None:
    query = (value or "").strip()
    if not query:
        return None

    if re.fullmatch(r"[A-Za-z]{3}", query):
        code = query.upper()
        return LocationResolution(original=query, code=code, label=code, source="codigo informado")

    result = _resolve_with_autocomplete(query, "pt")
    if result:
        return result

    result = _resolve_with_autocomplete(query, "en")
    if result:
        return result

    fallback_code = COUNTRY_MAIN_CODES.get(_normalize_key(query))
    if fallback_code:
        return LocationResolution(
            original=query,
            code=fallback_code,
            label=f"{query} ({fallback_code})",
            source="pais mapeado",
            location_type="country",
        )

    return None


def search_locations(value: str, limit: int = 8) -> list[LocationResolution]:
    query = (value or "").strip()
    if not query:
        return []

    results: list[LocationResolution] = []
    seen: set[str] = set()

    if re.fullmatch(r"[A-Za-z]{3}", query):
        code = query.upper()
        results.append(LocationResolution(original=query, code=code, label=f"{code} (codigo IATA)", source="codigo informado"))
        seen.add(code)

    for locale in ("pt", "en"):
        for item in _autocomplete_items(query, locale):
            if item.get("type") not in {"city", "airport"} or not item.get("code"):
                continue
            resolution = _resolution_from_item(query, item, "autocomplete")
            if resolution.code in seen:
                continue
            results.append(resolution)
            seen.add(resolution.code)
            if len(results) >= limit:
                return results

    fallback_code = COUNTRY_MAIN_CODES.get(_normalize_key(query))
    if fallback_code and fallback_code not in seen:
        results.append(
            LocationResolution(
                original=query,
                code=fallback_code,
                label=f"{query} ({fallback_code})",
                source="pais mapeado",
                location_type="country",
            )
        )

    return results[:limit]


@lru_cache(maxsize=256)
def _resolve_with_autocomplete(query: str, locale: str) -> LocationResolution | None:
    payload = _autocomplete_items(query, locale)
    if not payload:
        return None

    city_or_airport = _best_city_or_airport(payload, query)
    if city_or_airport:
        return _resolution_from_item(query, city_or_airport, "autocomplete")

    country = _best_country(payload, query)
    if country:
        country_code = str(country.get("code") or country.get("country_code") or "").upper()
        fallback_code = COUNTRY_MAIN_CODES.get(country_code) or COUNTRY_MAIN_CODES.get(_normalize_key(country.get("name", "")))
        if fallback_code:
            label = f"{country.get('name') or query} ({fallback_code})"
            return LocationResolution(query, fallback_code, label, "autocomplete pais", "country")

    return None


@lru_cache(maxsize=256)
def _autocomplete_items(query: str, locale: str) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            AUTOCOMPLETE_URL,
            params=[
                ("term", query),
                ("locale", locale),
                ("types[]", "city"),
                ("types[]", "airport"),
                ("types[]", "country"),
            ],
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []

    if not isinstance(payload, list):
        return []
    return payload


def _best_city_or_airport(items: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    options = [item for item in items if item.get("type") in {"city", "airport"} and item.get("code")]
    if not options:
        return None
    query_key = _normalize_key(query)

    def score(item: dict[str, Any]) -> tuple[int, int]:
        code = _normalize_key(item.get("code", ""))
        name = _normalize_key(item.get("name", ""))
        city_name = _normalize_key(item.get("city_name", ""))
        exact = int(query_key in {code, name, city_name})
        prefix = int(name.startswith(query_key) or city_name.startswith(query_key))
        return (exact + prefix, int(item.get("weight") or 0))

    return max(options, key=score)


def _best_country(items: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    options = [item for item in items if item.get("type") == "country"]
    if not options:
        return None
    query_key = _normalize_key(query)

    def score(item: dict[str, Any]) -> tuple[int, int]:
        code = _normalize_key(item.get("code", "") or item.get("country_code", ""))
        name = _normalize_key(item.get("name", "") or item.get("country_name", ""))
        exact = int(query_key in {code, name})
        prefix = int(name.startswith(query_key))
        return (exact + prefix, int(item.get("weight") or 0))

    return max(options, key=score)


def _resolution_from_item(query: str, item: dict[str, Any], source: str) -> LocationResolution:
    code = str(item.get("code")).upper()
    location_type = str(item.get("type") or "iata")
    name = item.get("name") or item.get("city_name") or code
    country = item.get("country_name") or item.get("country_code") or ""
    label = f"{name}, {country} ({code})" if country else f"{name} ({code})"
    return LocationResolution(query, code, label, source, location_type)


def _normalize_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.upper()).strip()
