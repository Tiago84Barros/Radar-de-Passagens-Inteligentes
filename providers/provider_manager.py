from __future__ import annotations

from datetime import date, timedelta
from random import Random
from typing import Any

from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError


def search_all_providers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    provider = TravelPayoutsProvider()
    results: list[dict[str, Any]] = []

    if provider.is_configured():
        try:
            results.extend(
                provider.search_flights(
                    origin=search_params["origin"],
                    destination=search_params["destination"],
                    departure_date=search_params["departure_date"],
                    return_date=search_params.get("return_date"),
                    currency=search_params.get("currency", "BRL"),
                    limit=search_params.get("limit", 20),
                )
            )
        except TravelPayoutsProviderError:
            results.extend(_demo_results(search_params, provider_name="travelpayouts_demo_fallback"))
    else:
        results.extend(_demo_results(search_params))

    return _sort_and_dedupe(results)


def _sort_and_dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple, dict[str, Any]] = {}
    for item in results:
        key = (
            item.get("provider"),
            item.get("origin"),
            item.get("destination"),
            item.get("departure_date"),
            item.get("return_date"),
            item.get("airline"),
            round(float(item.get("price") or 0), 2),
        )
        if key not in unique:
            unique[key] = item
    return sorted(unique.values(), key=lambda quote: float(quote.get("price") or 0))


def _demo_results(search_params: dict[str, Any], provider_name: str = "travelpayouts_demo") -> list[dict[str, Any]]:
    origin = str(search_params.get("origin") or "BEL").upper()
    destination = str(search_params.get("destination") or "LIS").upper()
    departure_date = _date_to_day(search_params.get("departure_date") or date.today() + timedelta(days=90))
    return_date = search_params.get("return_date")
    return_date_text = _date_to_day(return_date) if return_date else None
    currency = str(search_params.get("currency") or "BRL").upper()
    adults = int(search_params.get("adults") or search_params.get("passengers") or 1)
    seed = f"{origin}:{destination}:{departure_date}:{return_date_text}:{adults}"
    rng = Random(seed)
    airlines = ["TP", "LA", "AD", "G3", "IB"]
    results = []
    for index in range(6):
        price = (2800 + rng.randint(-450, 650) + index * 115) * adults
        stops = rng.choice([0, 1, 1, 2])
        results.append(
            {
                "provider": provider_name,
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
                "return_date": return_date_text,
                "airline": airlines[(rng.randint(0, 10) + index) % len(airlines)],
                "price": float(max(price, 499)),
                "currency": currency,
                "duration_minutes": rng.randint(430, 860),
                "stops": stops,
                "booking_link": "",
                "raw_payload": {"demo": True},
            }
        )
    return results


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
