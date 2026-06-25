from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus

import requests

from app.settings import get_settings
from providers.base_provider import BaseProvider


class SerpApiGoogleFlightsProvider(BaseProvider):
    """Google Flights results through SerpApi.

    The provider only accepts structured JSON returned by SerpApi. It never asks
    an LLM to infer prices from arbitrary pages.
    """

    name = "serpapi_google_flights"
    BASE_URL = "https://serpapi.com/search"

    def __init__(self, timeout: int = 35) -> None:
        self.settings = get_settings()
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.settings.serpapi_api_key)

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "BRL",
        adults: int = 1,
        limit: int = 20,
        max_stops: int | None = None,
        max_duration_minutes: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        params = self._build_params(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            currency=currency,
            adults=adults,
            max_stops=max_stops,
            max_duration_minutes=max_duration_minutes,
        )
        payload = self._fetch(params)
        results = self.normalize_response(
            payload,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            currency=currency,
        )
        return results[: max(int(limit or 20), 1)]

    def search_flexible_dates(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        flex_days: int = 0,
        currency: str = "BRL",
        adults: int = 1,
        limit_per_day: int = 5,
        max_stops: int | None = None,
        max_duration_minutes: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_configured() or flex_days <= 0:
            return []

        max_days = max(int(getattr(self.settings, "serpapi_max_flex_days", 2) or 2), 0)
        effective_flex = min(int(flex_days), max_days)
        if effective_flex <= 0:
            return []

        base_departure = _to_date(departure_date)
        base_return = _to_date(return_date) if return_date else None
        requested = _date_to_day(departure_date)
        results: list[dict[str, Any]] = []
        for offset in range(-effective_flex, effective_flex + 1):
            if offset == 0:
                continue
            day = base_departure + timedelta(days=offset)
            if day < date.today():
                continue
            return_day = (base_return + timedelta(days=offset)) if base_return else None
            try:
                day_results = self.search_flights(
                    origin=origin,
                    destination=destination,
                    departure_date=day,
                    return_date=return_day,
                    currency=currency,
                    adults=adults,
                    limit=limit_per_day,
                    max_stops=max_stops,
                    max_duration_minutes=max_duration_minutes,
                )
            except SerpApiProviderError:
                continue
            for item in day_results:
                item["date_match"] = "flex_search"
                item["date_offset_days"] = offset
                item["requested_date"] = requested
            results.extend(day_results)
        return results

    def _build_params(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None,
        currency: str,
        adults: int,
        max_stops: int | None,
        max_duration_minutes: int | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google_flights",
            "api_key": self.settings.serpapi_api_key,
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": _date_to_day(departure_date),
            "type": "1" if return_date else "2",
            "currency": str(currency or "BRL").upper(),
            "hl": "pt",
            "gl": "br",
            "adults": max(int(adults or 1), 1),
            "sort_by": "2",
            "deep_search": _bool_param(getattr(self.settings, "serpapi_deep_search", True)),
            "no_cache": _bool_param(getattr(self.settings, "serpapi_no_cache", True)),
            "output": "json",
        }
        if return_date:
            params["return_date"] = _date_to_day(return_date)
        stops = _serpapi_stops(max_stops)
        if stops is not None:
            params["stops"] = stops
        if max_duration_minutes:
            params["max_duration"] = int(max_duration_minutes)
        return params

    def _fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=self.timeout)
            if response.status_code in {401, 403}:
                raise SerpApiProviderError(
                    "Chave da SerpApi recusada. Confira o secret SERPAPI_API_KEY.",
                    status_code=response.status_code,
                )
            response.raise_for_status()
            payload = response.json()
        except SerpApiProviderError:
            raise
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise SerpApiProviderError(
                "Nao foi possivel consultar a SerpApi Google Flights agora.",
                status_code=status_code,
            ) from exc
        except ValueError as exc:
            raise SerpApiProviderError("A SerpApi retornou uma resposta invalida.") from exc

        if not isinstance(payload, dict):
            raise SerpApiProviderError("A SerpApi retornou uma resposta inesperada.")
        if payload.get("error"):
            raise SerpApiProviderError(f"A SerpApi recusou a consulta: {_safe_error_text(payload.get('error'))}")
        return payload

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        metadata = payload.get("search_metadata") if isinstance(payload.get("search_metadata"), dict) else {}
        source_url = (
            str(metadata.get("google_flights_url") or "").strip()
            or _google_flights_search_url(
                kwargs["origin"],
                kwargs["destination"],
                kwargs["departure_date"],
                kwargs.get("return_date"),
            )
        )
        results: list[dict[str, Any]] = []
        for collection in ("best_flights", "other_flights"):
            items = payload.get(collection) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = self._normalize_item(item, kwargs, source_url, collection, metadata)
                if normalized:
                    results.append(normalized)
        return results

    def _normalize_item(
        self,
        item: dict[str, Any],
        kwargs: dict[str, Any],
        source_url: str,
        collection: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        price = _parse_price(item.get("price"))
        flights = item.get("flights") if isinstance(item.get("flights"), list) else []
        if price is None or not flights:
            return None

        first = flights[0] if isinstance(flights[0], dict) else {}
        last = flights[-1] if isinstance(flights[-1], dict) else {}
        dep_airport = first.get("departure_airport") if isinstance(first.get("departure_airport"), dict) else {}
        arr_airport = last.get("arrival_airport") if isinstance(last.get("arrival_airport"), dict) else {}
        dep_time = str(dep_airport.get("time") or kwargs["departure_date"])
        arr_time = str(arr_airport.get("time") or "")
        return_date = _date_to_day(kwargs["return_date"]) if kwargs.get("return_date") else None

        airline = item.get("airline") or _join_unique(f.get("airline") for f in flights if isinstance(f, dict))
        flight_number = _join_unique(f.get("flight_number") for f in flights if isinstance(f, dict))
        layovers = item.get("layovers") if isinstance(item.get("layovers"), list) else []
        stops = len(layovers) if layovers else max(len(flights) - 1, 0)

        return {
            "provider": self.name,
            "source": self.name,
            "source_name": "Google Flights via SerpApi",
            "source_url": source_url,
            "source_verified": True,
            "origin": str(dep_airport.get("id") or kwargs["origin"]).upper(),
            "destination": str(arr_airport.get("id") or kwargs["destination"]).upper(),
            "departure_date": _date_to_day(dep_time),
            "departure_at": dep_time,
            "return_date": return_date,
            "return_at": return_date,
            "airline": str(airline or ""),
            "flight_number": str(flight_number or ""),
            "price": float(price),
            "currency": str(kwargs.get("currency") or "BRL").upper(),
            "duration_minutes": item.get("total_duration") or _sum_duration(flights),
            "stops": stops,
            "booking_link": source_url,
            "booking_token": item.get("booking_token"),
            "departure_token": item.get("departure_token"),
            "connections": _connections_from_layovers(layovers),
            "raw_payload": {
                "collection": collection,
                "search_id": metadata.get("id"),
                "item": item,
            },
        }


class SerpApiProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _serpapi_stops(max_stops: int | None) -> str | None:
    if max_stops is None:
        return None
    value = int(max_stops)
    if value <= 0:
        return "1"
    if value == 1:
        return "2"
    return "3"


def _bool_param(value: bool) -> str:
    return "true" if bool(value) else "false"


def _parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit() or ch in {",", "."})
    if not digits:
        return None
    if "," in digits and "." in digits:
        digits = digits.replace(".", "").replace(",", ".")
    elif "," in digits:
        digits = digits.replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]


def _to_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(_date_to_day(value))


def _join_unique(values: Any) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return " + ".join(seen)


def _sum_duration(flights: list[Any]) -> int | None:
    total = 0
    found = False
    for flight in flights:
        if isinstance(flight, dict) and flight.get("duration") is not None:
            total += int(flight["duration"])
            found = True
    return total if found else None


def _connections_from_layovers(layovers: list[Any]) -> list[dict[str, Any]]:
    connections: list[dict[str, Any]] = []
    for layover in layovers:
        if not isinstance(layover, dict):
            continue
        connections.append(
            {
                "airport": layover.get("id") or layover.get("name") or "",
                "duration_minutes": layover.get("duration"),
            }
        )
    return connections


def _google_flights_search_url(
    origin: str,
    destination: str,
    departure_date: date | str,
    return_date: date | str | None,
) -> str:
    query = f"Flights from {origin.upper()} to {destination.upper()} on {_date_to_day(departure_date)}"
    if return_date:
        query += f" returning {_date_to_day(return_date)}"
    return f"https://www.google.com/travel/flights?q={quote_plus(query)}&hl=pt-BR"


def _safe_error_text(value: Any) -> str:
    text = str(value)
    token = get_settings().serpapi_api_key or ""
    if token:
        text = text.replace(token, "[token oculto]")
    return text[:240]
