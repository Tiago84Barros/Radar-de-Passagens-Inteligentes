"""Orquestra a busca de tarifas usando somente APIs configuradas.

Scraping direto e LLMs como fonte de preco ficam fora do motor principal.

Fontes ativas:
- SerpApi Google Flights = fonte API principal para resultados estruturados.
- Travelpayouts = fonte API complementar/cache e base de rotas combinadas.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from providers.serpapi_provider import SerpApiGoogleFlightsProvider, SerpApiProviderError
from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError


_LAST_PROVIDER_DIAGNOSTIC: dict[str, Any] = {
    "provider": "apis",
    "status": "not_run",
    "message": "Nenhuma consulta executada ainda.",
}


def search_all_providers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """Search configured flight APIs and return only structured provider data."""
    global _LAST_PROVIDER_DIAGNOSTIC

    is_segment = bool(search_params.get("_is_segment"))
    serpapi = SerpApiGoogleFlightsProvider()
    travelpayouts = TravelPayoutsProvider()
    results: list[dict[str, Any]] = []
    _LAST_PROVIDER_DIAGNOSTIC = {
        "provider": "apis",
        "status": "api_empty",
        "message": "",
    }

    if serpapi.is_configured():
        try:
            serp_results = serpapi.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=search_params.get("return_date"),
                currency=search_params.get("currency", "BRL"),
                adults=int(search_params.get("adults") or search_params.get("passengers") or 1),
                limit=search_params.get("limit", 20),
                max_stops=search_params.get("max_stops"),
                max_duration_minutes=search_params.get("max_duration_minutes"),
            )
            serp_results = _filter_to_requested_dates(serp_results, search_params)
            results.extend(serp_results)
            _LAST_PROVIDER_DIAGNOSTIC["serpapi"] = (
                f"{len(serp_results)} cotacao(oes) via Google Flights/SerpApi."
                if serp_results
                else "SerpApi sem cotacoes para esta rota/data."
            )
        except SerpApiProviderError as exc:
            message = str(exc)
            if exc.status_code:
                message = f"{message} HTTP {exc.status_code}."
            _LAST_PROVIDER_DIAGNOSTIC["serpapi_erro"] = message
    else:
        _LAST_PROVIDER_DIAGNOSTIC["serpapi"] = "SERPAPI_API_KEY ausente."

    if travelpayouts.is_configured():
        try:
            tp_results = travelpayouts.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=search_params.get("return_date"),
                currency=search_params.get("currency", "BRL"),
                limit=search_params.get("limit", 20),
            )
            tp_results = _filter_to_requested_dates(tp_results, search_params)
            results.extend(tp_results)
            _LAST_PROVIDER_DIAGNOSTIC["travelpayouts"] = (
                f"{len(tp_results)} cotacao(oes) via Travelpayouts."
                if tp_results
                else "Travelpayouts sem cotacoes para esta rota/data."
            )
        except TravelPayoutsProviderError as exc:
            message = str(exc)
            if exc.status_code:
                message = f"{message} HTTP {exc.status_code}."
            _LAST_PROVIDER_DIAGNOSTIC["travelpayouts_erro"] = message
    else:
        _LAST_PROVIDER_DIAGNOSTIC["travelpayouts"] = "TRAVELPAYOUTS_API_TOKEN ausente."

    flex_days = int(search_params.get("date_flex_days") or 0)
    if not is_segment and 0 < flex_days < 14:
        if serpapi.is_configured():
            try:
                serp_flex = serpapi.search_flexible_dates(
                    origin=search_params["origin"],
                    destination=search_params["destination"],
                    departure_date=search_params["departure_date"],
                    return_date=search_params.get("return_date"),
                    flex_days=flex_days,
                    currency=search_params.get("currency", "BRL"),
                    adults=int(search_params.get("adults") or search_params.get("passengers") or 1),
                    limit_per_day=5,
                    max_stops=search_params.get("max_stops"),
                    max_duration_minutes=search_params.get("max_duration_minutes"),
                )
                serp_flex = _filter_to_requested_dates(serp_flex, search_params)
                if serp_flex:
                    results.extend(serp_flex)
                    _LAST_PROVIDER_DIAGNOSTIC["serpapi_date_flex"] = (
                        f"{len(serp_flex)} cotacao(oes) extras via SerpApi em datas vizinhas."
                    )
            except SerpApiProviderError:
                pass
        if travelpayouts.is_configured():
            try:
                tp_flex = travelpayouts.search_flexible_dates(
                    origin=search_params["origin"],
                    destination=search_params["destination"],
                    departure_date=search_params["departure_date"],
                    return_date=search_params.get("return_date"),
                    flex_days=flex_days,
                    currency=search_params.get("currency", "BRL"),
                    limit_per_day=10,
                )
                tp_flex = _filter_to_requested_dates(tp_flex, search_params)
                if tp_flex:
                    results.extend(tp_flex)
                    _LAST_PROVIDER_DIAGNOSTIC["travelpayouts_date_flex"] = (
                        f"{len(tp_flex)} cotacao(oes) extras via Travelpayouts em datas vizinhas."
                    )
            except TravelPayoutsProviderError:
                pass

    direct_results = _sort_and_dedupe(_filter_to_requested_dates(results, search_params))

    max_hubs = int(search_params.get("max_connection_hubs", 4) or 0)
    if not is_segment and max_hubs > 0:
        try:
            from services.multi_segment_search import search_via_connections

            combined = search_via_connections(
                search_params=search_params,
                direct_search_fn=_search_segment,
                max_hubs=max_hubs,
                direct_results=direct_results,
            )
            if combined:
                direct_results = _sort_and_dedupe(_filter_to_requested_dates(direct_results + combined, search_params))
                hub_info = ", ".join(c.get("via_hub", "?") for c in combined)
                _LAST_PROVIDER_DIAGNOSTIC["multi_segment"] = (
                    f"{len(combined)} rota(s) combinada(s) encontrada(s) via {hub_info}."
                )
        except Exception:
            pass

    if not direct_results:
        if not serpapi.is_configured() and not travelpayouts.is_configured():
            message = "Nenhuma API de passagens configurada. Configure SERPAPI_API_KEY ou TRAVELPAYOUTS_API_TOKEN."
        else:
            message = "Nenhuma tarifa foi retornada pelas APIs configuradas."
        _LAST_PROVIDER_DIAGNOSTIC.update(
            provider="none",
            status="no_confirmed_source",
            message=message,
            coverage="sem_cobertura_real",
            coverage_note="Nenhuma API configurada confirmou tarifa para esta rota/data.",
        )
    else:
        _LAST_PROVIDER_DIAGNOSTIC.update(
            provider="apis",
            status="api_ok",
            message=f"{len(direct_results)} tarifa(s) confirmada(s) por API.",
            coverage="ok",
        )

    for offer in direct_results:
        offer["source_confidence"] = _source_confidence(offer)

    return direct_results


def _source_confidence(offer: dict[str, Any]) -> str:
    src = str(offer.get("provider") or offer.get("source") or "").lower()
    if any(m in src for m in ("demo", "mock", "fallback")):
        return "demo"
    if any(m in src for m in ("travelpayouts", "serpapi", "google_flights", "combinado")):
        return "real"
    if offer.get("source_verified") is True and offer.get("source_url"):
        return "verified"
    return "unverified"


def _search_segment(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """Search a one-way segment for multi-ticket combinations.

    This intentionally uses Travelpayouts only to avoid multiplying paid SerpApi
    calls across every hub candidate.
    """
    provider = TravelPayoutsProvider()
    if provider.is_configured():
        try:
            segment_results = provider.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=None,
                currency=search_params.get("currency", "BRL"),
                limit=search_params.get("limit", 5),
            )
            return _filter_to_requested_dates(segment_results, search_params)
        except TravelPayoutsProviderError:
            pass
    return []


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
            return []
    return []


def get_last_provider_diagnostic() -> dict[str, Any]:
    return dict(_LAST_PROVIDER_DIAGNOSTIC)


def _sort_and_dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple, dict[str, Any]] = {}
    for item in results:
        dep, ret = item.get("departure_date"), item.get("return_date")
        if dep and ret and str(ret)[:10] <= str(dep)[:10]:
            item = {**item, "return_date": None, "price_note": item.get("price_note") or "preco_somente_ida"}
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
    return sorted(unique.values(), key=lambda q: float(q.get("price") or 0))


def _filter_to_requested_dates(results: list[dict[str, Any]], search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep only fares inside the user-approved date window."""
    requested_dep = _parse_day(search_params.get("departure_date"))
    requested_ret = _parse_day(search_params.get("return_date"))
    min_departure = _parse_day(search_params.get("min_departure_date"))
    flex_days = max(int(search_params.get("date_flex_days") or 0), 0)
    flexible_month = bool(search_params.get("flexible_month")) or flex_days >= 14

    filtered: list[dict[str, Any]] = []
    for item in results:
        dep = _parse_day(item.get("departure_date"))
        ret = _parse_day(item.get("return_date"))
        if dep is None:
            continue
        if min_departure is not None and dep <= min_departure:
            continue
        if requested_dep is not None and not _within_requested_window(dep, requested_dep, flex_days, flexible_month):
            continue
        if requested_ret is not None:
            if ret is None or ret <= dep:
                continue
            if not _within_requested_window(ret, requested_ret, flex_days, flexible_month):
                continue
        filtered.append(item)
    return filtered


def _within_requested_window(actual: date, requested: date, flex_days: int, flexible_month: bool) -> bool:
    if flexible_month and actual.year == requested.year and actual.month == requested.month:
        return True
    return abs((actual - requested).days) <= flex_days


def _parse_day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
