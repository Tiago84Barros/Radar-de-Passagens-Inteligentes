"""Orquestra a busca de tarifas usando exclusivamente as APIs configuradas.

Scraping desativado. O app usa somente APIs configuradas.

Papeis bem definidos:
- Gemini + Google Search = provider primario (cobre rotas/datas que a
  Travelpayouts costuma nao ter, como rotas de baixo trafego ou nicho).
- Travelpayouts = apoio/fallback; so entra quando o Gemini nao retorna
  cotacoes para a rota/data.
"""
from __future__ import annotations

from datetime import date, timedelta
from random import Random
from typing import Any

from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError


_LAST_PROVIDER_DIAGNOSTIC: dict[str, Any] = {
    "provider": "travelpayouts",
    "status": "not_run",
    "message": "Nenhuma consulta executada ainda.",
}


def _search_gemini(search_params: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Gemini + Google Search — provider primario de busca de tarifas.
    Failure-safe: retorna ([], msg) em qualquer erro, nunca derruba o pipeline."""
    try:
        from providers.gemini_search_provider import GeminiSearchProvider
        gemini = GeminiSearchProvider()
        if not gemini.is_configured():
            return [], "nao_configurado"
        results = gemini.search_flights(
            origin=search_params["origin"],
            destination=search_params["destination"],
            departure_date=search_params["departure_date"],
            return_date=search_params.get("return_date"),
            currency=search_params.get("currency", "BRL"),
            adults=int(search_params.get("adults") or search_params.get("passengers") or 1),
            limit=search_params.get("limit", 20),
            flexible_month=bool(search_params.get("flexible_month")),
        )
        for r in results:
            r.setdefault("source", "gemini_web_search")
            r.setdefault("provider", "gemini_web_search")
        msg = f"{len(results)} cotacao(oes) via Gemini" if results else "Gemini nao retornou cotacoes"
        return results, msg
    except Exception as exc:  # noqa: BLE001
        return [], f"erro Gemini: {str(exc)[:120]}"


def _has_real_results(results: list[dict[str, Any]]) -> bool:
    """True se ha ao menos uma cotacao de fonte real (nao demo/mock/fallback)."""
    for r in results:
        src = str(r.get("provider") or r.get("source") or "").lower()
        if src and not any(m in src for m in ("demo", "mock", "fallback")):
            return True
    return False


def search_all_providers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Busca tarifas usando o Gemini (busca web) como provider primario e a
    Travelpayouts como apoio/fallback — incluindo conexoes multi-segmento
    pela malha aerea brasileira (quando esta nao e ja uma chamada de segmento).
    """
    global _LAST_PROVIDER_DIAGNOSTIC

    # Prevent recursive multi-segment calls
    is_segment = bool(search_params.get("_is_segment"))

    results: list[dict[str, Any]] = []

    # ── Gemini (provider primario) ────────────────────────────────────────────
    gemini_results, gemini_msg = _search_gemini(search_params)
    results.extend(gemini_results)
    if gemini_results:
        _LAST_PROVIDER_DIAGNOSTIC = {
            "provider": "gemini_web_search",
            "status": "real_ok",
            "message": f"{len(gemini_results)} cotacao(oes) recebidas via Gemini (busca web).",
        }
    elif gemini_msg == "nao_configurado":
        _LAST_PROVIDER_DIAGNOSTIC = {
            "provider": "gemini_web_search",
            "status": "not_configured",
            "message": "Gemini nao configurado (GEMINI_API_KEY ausente); tentando Travelpayouts.",
        }
    else:
        _LAST_PROVIDER_DIAGNOSTIC = {
            "provider": "gemini_web_search",
            "status": "real_empty",
            "message": gemini_msg,
        }

    # ── Travelpayouts (apoio/fallback) — so aciona quando o Gemini ainda nao
    # trouxe nenhuma cotacao real para a rota/data.
    tp_apoio_msg = "nao_acionado"
    if not is_segment and not _has_real_results(results):
        provider = TravelPayoutsProvider()
        if provider.is_configured():
            try:
                tp_results = provider.search_flights(
                    origin=search_params["origin"],
                    destination=search_params["destination"],
                    departure_date=search_params["departure_date"],
                    return_date=search_params.get("return_date"),
                    currency=search_params.get("currency", "BRL"),
                    limit=search_params.get("limit", 20),
                )
                results.extend(tp_results)
                tp_apoio_msg = (
                    f"{len(tp_results)} cotacao(oes) via Travelpayouts (apoio)"
                    if tp_results else "Travelpayouts nao retornou cotacoes de apoio"
                )
            except TravelPayoutsProviderError as exc:
                message = str(exc)
                if exc.status_code:
                    message = f"{message} HTTP {exc.status_code}."
                tp_apoio_msg = f"erro Travelpayouts: {message}"
                if not results:
                    results.extend(_demo_results(search_params, provider_name="travelpayouts_demo_fallback", fallback_reason=message))
        else:
            tp_apoio_msg = "nao_configurado"
            if not results:
                _LAST_PROVIDER_DIAGNOSTIC = {
                    "provider": "travelpayouts",
                    "status": "demo_no_token",
                    "message": "Gemini nao retornou cotacoes e TRAVELPAYOUTS_API_TOKEN nao configurado; usando modo demonstracao.",
                }
                results.extend(_demo_results(search_params))

    if tp_apoio_msg != "nao_acionado":
        _LAST_PROVIDER_DIAGNOSTIC["travelpayouts_apoio"] = tp_apoio_msg

    if gemini_results and _has_real_results(results) and len(results) > len(gemini_results):
        _LAST_PROVIDER_DIAGNOSTIC = {
            "provider": "hybrid",
            "status": "hybrid_ok",
            "message": (
                f"{len(results)} cotacao(oes) coletadas: Gemini (busca web, fonte primaria) "
                f"+ Travelpayouts (apoio)."
            ),
            "travelpayouts_apoio": tp_apoio_msg,
        }

    # ── Marcador honesto de cobertura ─────────────────────────────────────────
    # Distingue "rota sem cobertura nas fontes reais" de "erro/demo", para a UI
    # poder avisar com clareza em vez de um vazio ambiguo.
    if not _has_real_results(results):
        _LAST_PROVIDER_DIAGNOSTIC["coverage"] = "sem_cobertura_real"
        _LAST_PROVIDER_DIAGNOSTIC["coverage_note"] = (
            "Nenhuma fonte real (Travelpayouts/Gemini) tem dados para esta rota/data. "
            "Rotas de baixo trafego ou internacionais de nicho podem nao ter cobertura "
            "gratuita disponivel."
        )
    else:
        _LAST_PROVIDER_DIAGNOSTIC["coverage"] = "ok"

    direct_results = _sort_and_dedupe(results)

    # ── Multi-segment search via Brazilian hubs (usa Travelpayouts) ──────────
    if not is_segment:
        try:
            from services.multi_segment_search import search_via_connections
            combined = search_via_connections(
                search_params=search_params,
                direct_search_fn=_search_segment,
                max_hubs=2,
                direct_results=direct_results,
            )
            if combined:
                direct_results = _sort_and_dedupe(direct_results + combined)
                hub_info = ", ".join(
                    c.get("via_hub", "?") for c in combined
                )
                _LAST_PROVIDER_DIAGNOSTIC["multi_segment"] = (
                    f"{len(combined)} rota(s) combinada(s) encontrada(s) via {hub_info}."
                )
        except Exception:
            # Multi-segment failure must never break the main search
            pass

    return direct_results


def _search_segment(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Search a single one-way segment.  Used by multi_segment_search as the
    provider function for each leg — never triggers multi-segment recursion.
    """
    gemini_results, _ = _search_gemini(search_params)
    if gemini_results:
        return gemini_results

    provider = TravelPayoutsProvider()
    if provider.is_configured():
        try:
            return provider.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=None,   # segments are always one-way
                currency=search_params.get("currency", "BRL"),
                limit=search_params.get("limit", 5),
            )
        except TravelPayoutsProviderError:
            pass
    # Demo fallback for segment
    return _demo_results(search_params)


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
    return sorted(unique.values(), key=lambda q: float(q.get("price") or 0))


def _demo_results(
    search_params: dict[str, Any],
    provider_name: str = "travelpayouts_demo",
    fallback_reason: str | None = None,
) -> list[dict[str, Any]]:
    """Generate realistic demo results.  Domestic routes get lower price ranges."""
    from services.air_network import get_region

    origin = str(search_params.get("origin") or "GRU").upper()
    destination = str(search_params.get("destination") or "LIS").upper()
    departure_date = _date_to_day(search_params.get("departure_date") or date.today() + timedelta(days=90))
    return_date = search_params.get("return_date")
    return_date_text = _date_to_day(return_date) if return_date else None
    currency = str(search_params.get("currency") or "BRL").upper()
    adults = int(search_params.get("adults") or search_params.get("passengers") or 1)

    seed = f"{origin}:{destination}:{departure_date}:{return_date_text}:{adults}"
    rng = Random(seed)

    # ── Price range: domestic vs international ─────────────────────────────
    origin_region = get_region(origin)
    dest_region = get_region(destination)
    both_domestic = origin_region is not None and dest_region is not None

    if both_domestic:
        # Realistic Brazilian domestic fares (per person one-way)
        base_price = 450 + rng.randint(-200, 350)
    else:
        base_price = 2_800 + rng.randint(-450, 650)

    airlines = ["LA", "G3", "AD", "TP", "IB"] if not both_domestic else ["LA", "G3", "AD", "LA", "G3"]
    results = []
    for index in range(6):
        price = (base_price + index * (60 if both_domestic else 115)) * adults
        stops = rng.choice([0, 0, 1, 1, 1, 2])
        results.append(
            {
                "provider": provider_name,
                "source": provider_name,
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
                "return_date": return_date_text,
                "airline": airlines[(rng.randint(0, 10) + index) % len(airlines)],
                "price": float(max(price, 199 if both_domestic else 499)),
                "currency": currency,
                "duration_minutes": rng.randint(60, 240) if both_domestic else rng.randint(430, 860),
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
