from __future__ import annotations

from datetime import date, timedelta
from random import Random
from typing import Any

from scrapers.scraper_manager import get_last_scraper_diagnostics, search_all_scrapers
from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError


_LAST_PROVIDER_DIAGNOSTIC: dict[str, Any] = {
    "provider": "travelpayouts",
    "status": "not_run",
    "message": "Nenhuma consulta executada ainda.",
}


def search_all_providers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    global _LAST_PROVIDER_DIAGNOSTIC
    provider = TravelPayoutsProvider()
    results: list[dict[str, Any]] = []

    if provider.is_configured():
        try:
            travelpayouts_results = provider.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=search_params.get("return_date"),
                currency=search_params.get("currency", "BRL"),
                limit=search_params.get("limit", 20),
            )
            results.extend(travelpayouts_results)
            if travelpayouts_results:
                _LAST_PROVIDER_DIAGNOSTIC = {
                    "provider": provider.name,
                    "status": "real_ok",
                    "message": f"{len(travelpayouts_results)} cotacao(oes) reais recebidas da Travelpayouts.",
                }
            else:
                _LAST_PROVIDER_DIAGNOSTIC = {
                    "provider": provider.name,
                    "status": "real_empty",
                    "message": "Travelpayouts respondeu, mas nao retornou cotacoes para essa rota/data.",
                }
        except TravelPayoutsProviderError as exc:
            message = str(exc)
            if exc.status_code:
                message = f"{message} HTTP {exc.status_code}."
            _LAST_PROVIDER_DIAGNOSTIC = {
                "provider": provider.name,
                "status": "real_failed_fallback",
                "message": message,
            }
            results.extend(_demo_results(search_params, provider_name="travelpayouts_demo_fallback", fallback_reason=message))
    else:
        _LAST_PROVIDER_DIAGNOSTIC = {
            "provider": provider.name,
            "status": "demo_no_token",
            "message": "TRAVELPAYOUTS_API_TOKEN nao configurado; usando modo demonstracao.",
        }
        results.extend(_demo_results(search_params))

    scraper_results = search_all_scrapers(search_params)
    results.extend(scraper_results)
    scraper_diagnostics = get_last_scraper_diagnostics()
    if scraper_results:
        _LAST_PROVIDER_DIAGNOSTIC = {
            "provider": "hybrid",
            "status": "hybrid_ok",
            "message": f"{len(results)} cotacao(oes) coletadas entre Travelpayouts e scrapers.",
            "scrapers": scraper_diagnostics,
        }
    elif scraper_diagnostics:
        _LAST_PROVIDER_DIAGNOSTIC["scrapers"] = scraper_diagnostics

    return _sort_and_dedupe(results)


def search_year_price_calendar(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    provider = TravelPayoutsProvider()
    if provider.is_configured():
        try:
            return _sort_and_dedupe(
                provider.search_year_flights(
                    origin=search_params["origin"],
                    destination=search_params["destination"],
                    start_date=search_params.get("departure_date") or date.today(),
                    return_date=search_params.get("return_date"),
                    currency=search_params.get("currency", "BRL"),
                    limit_per_month=search_params.get("year_limit_per_month", 100),
                )
            )
        except TravelPayoutsProviderError:
            return _sort_and_dedupe(_demo_year_results(search_params))
    return _sort_and_dedupe(_demo_year_results(search_params))


def get_last_provider_diagnostic() -> dict[str, Any]:
    return dict(_LAST_PROVIDER_DIAGNOSTIC)


def _sort_and_dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple, dict[str, Any]] = {}
    for item in results:
        key = (
            item.get("provider"),
            item.get("source"),
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


def _demo_results(
    search_params: dict[str, Any],
    provider_name: str = "travelpayouts_demo",
    fallback_reason: str | None = None,
) -> list[dict[str, Any]]:
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
                "source": provider_name,
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
                "raw_payload": {"demo": True, "fallback_reason": fallback_reason},
            }
        )
    return results


def _demo_year_results(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    origin = str(search_params.get("origin") or "BEL").upper()
    destination = str(search_params.get("destination") or "LIS").upper()
    start = _date_to_date(search_params.get("departure_date") or date.today())
    currency = str(search_params.get("currency") or "BRL").upper()
    return_date = search_params.get("return_date")
    rng = Random(f"year:{origin}:{destination}:{start}:{return_date}:{currency}")
    airlines = ["Azul", "GOL", "LATAM", "TAP", "Iberia"]
    results: list[dict[str, Any]] = []
    for week in range(0, 52):
        departure = start + timedelta(days=week * 7)
        seasonal = 280 * (1 if departure.month in {1, 7, 12} else 0)
        for airline in airlines:
            price = 900 + rng.randint(0, 1100) + seasonal + week * rng.randint(-3, 5)
            results.append(
                {
                    "provider": "travelpayouts_demo_calendar",
                    "source": "travelpayouts_demo_calendar",
                    "origin": origin,
                    "destination": destination,
                    "departure_date": _date_to_day(departure),
                    "return_date": _date_to_day(return_date) if return_date else None,
                    "airline": airline,
                    "price": float(max(price, 299)),
                    "currency": currency,
                    "duration_minutes": None,
                    "stops": None,
                    "booking_link": "",
                    "raw_payload": {"demo": True, "calendar_collection": "year"},
                }
            )
    return results


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]


def _date_to_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(_date_to_day(value))
