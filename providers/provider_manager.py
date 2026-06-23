"""Orquestra a busca de tarifas usando exclusivamente as APIs configuradas.

Scraping desativado. O app usa somente APIs configuradas.

Papeis bem definidos:
- Travelpayouts = fonte de precos reais (provider primario).
- Gemini = apoio de analise/organizacao/fallback via busca web — nunca fonte
  primaria de tarifa real; so entra quando a Travelpayouts nao retorna nada.
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
        # Ativa busca por mes inteiro quando: (a) o usuario marcou o checkbox
        # "Pesquisar o mes inteiro" ou (b) selecionou tolerancia >= 14 dias no
        # slider — ambos sinalizam que datas flexiveis sao bem-vindas.
        flex_days = int(search_params.get("date_flex_days") or 0)
        flexible_month = bool(search_params.get("flexible_month")) or flex_days >= 14
        results = gemini.search_flights(
            origin=search_params["origin"],
            destination=search_params["destination"],
            departure_date=search_params["departure_date"],
            return_date=search_params.get("return_date"),
            currency=search_params.get("currency", "BRL"),
            adults=int(search_params.get("adults") or search_params.get("passengers") or 1),
            limit=search_params.get("limit", 20),
            flexible_month=flexible_month,
        )
        for r in results:
            r.setdefault("source", "gemini_web_search")
            r.setdefault("provider", "gemini_web_search")
        msg = f"{len(results)} cotacao(oes) via Gemini" if results else "Gemini nao retornou cotacoes"
        return results, msg
    except Exception as exc:  # noqa: BLE001
        return [], f"erro Gemini: {str(exc)[:120]}"


def _search_openai(search_params: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """OpenAI + web search — segundo motor de busca, mesmo contrato do Gemini.
    Failure-safe: retorna ([], msg) em qualquer erro, nunca derruba o pipeline."""
    try:
        from providers.openai_search_provider import OpenAISearchProvider
        oai = OpenAISearchProvider()
        if not oai.is_configured():
            return [], "nao_configurado"
        flex_days = int(search_params.get("date_flex_days") or 0)
        flexible_month = bool(search_params.get("flexible_month")) or flex_days >= 14
        results = oai.search_flights(
            origin=search_params["origin"],
            destination=search_params["destination"],
            departure_date=search_params["departure_date"],
            return_date=search_params.get("return_date"),
            currency=search_params.get("currency", "BRL"),
            adults=int(search_params.get("adults") or search_params.get("passengers") or 1),
            limit=search_params.get("limit", 20),
            flexible_month=flexible_month,
        )
        for r in results:
            r.setdefault("source", "openai_web_search")
            r.setdefault("provider", "openai_web_search")
        msg = f"{len(results)} cotacao(oes) via OpenAI" if results else "OpenAI nao retornou cotacoes"
        return results, msg
    except Exception as exc:  # noqa: BLE001
        return [], f"erro OpenAI: {str(exc)[:120]}"


def _has_real_results(results: list[dict[str, Any]]) -> bool:
    """True only for published Travelpayouts prices or combinations of them."""
    for r in results:
        src = str(r.get("provider") or r.get("source") or "").lower()
        if any(m in src for m in ("demo", "mock", "fallback")):
            continue
        if "travelpayouts" in src or "combinado" in src:
            return True
    return False


def search_all_providers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Hierarquia de confiabilidade: a TRAVELPAYOUTS (preço real, não alucina) é a
    fonte PRIMÁRIA. As IAs de busca web (Gemini/OpenAI) só entram como hipótese
    quando não há preço real para a rota/data — ou quando o usuário marca
    ``force_web_search`` — e suas cotações são sempre marcadas como NÃO
    validadas (``source_confidence = unverified``). Inclui conexões
    multi-segmento pela malha aérea (preços reais da Travelpayouts).
    """
    global _LAST_PROVIDER_DIAGNOSTIC

    # Prevent recursive multi-segment calls
    is_segment = bool(search_params.get("_is_segment"))
    force_web = bool(search_params.get("force_web_search"))

    provider = TravelPayoutsProvider()
    results: list[dict[str, Any]] = []
    _LAST_PROVIDER_DIAGNOSTIC = {"provider": "travelpayouts", "status": "real_empty", "message": ""}

    # ── Travelpayouts (PRIMÁRIO — preço real publicado) ───────────────────────
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
            if tp_results:
                _LAST_PROVIDER_DIAGNOSTIC = {
                    "provider": "travelpayouts",
                    "status": "real_ok",
                    "message": f"{len(tp_results)} cotação(ões) reais via Travelpayouts.",
                }
            else:
                _LAST_PROVIDER_DIAGNOSTIC["message"] = "Travelpayouts sem cotações para esta rota/data."
        except TravelPayoutsProviderError as exc:
            message = str(exc)
            if exc.status_code:
                message = f"{message} HTTP {exc.status_code}."
            _LAST_PROVIDER_DIAGNOSTIC["travelpayouts_erro"] = message
    else:
        _LAST_PROVIDER_DIAGNOSTIC["message"] = "TRAVELPAYOUTS_TOKEN ausente."

    has_real = _has_real_results(results)

    # ── IA (Gemini/OpenAI) — só hipótese, marcada NÃO validada ────────────────
    # Roda quando não há preço real (cobre rotas de nicho/datas distantes que a
    # Travelpayouts não tem) ou quando o usuário força a busca web.
    if force_web or not has_real:
        gemini_results, gemini_msg = _search_gemini(search_params)
        results.extend(gemini_results)
        if gemini_results:
            _LAST_PROVIDER_DIAGNOSTIC["gemini"] = f"{len(gemini_results)} hipótese(s) via Gemini (não validadas)."
            if not has_real:
                _LAST_PROVIDER_DIAGNOSTIC.update(
                    provider="gemini_web_search",
                    status="real_ok",
                    message=f"{len(gemini_results)} hipótese(s) via Gemini — sem preço real para a rota.",
                )
        elif gemini_msg != "nao_configurado":
            _LAST_PROVIDER_DIAGNOSTIC["gemini"] = gemini_msg

        openai_results, openai_msg = _search_openai(search_params)
        results.extend(openai_results)
        if openai_results:
            _LAST_PROVIDER_DIAGNOSTIC["openai"] = f"{len(openai_results)} hipótese(s) via OpenAI (não validadas)."
        elif openai_msg != "nao_configurado":
            _LAST_PROVIDER_DIAGNOSTIC["openai"] = openai_msg
    else:
        _LAST_PROVIDER_DIAGNOSTIC["ai_skipped"] = (
            "IA não consultada: há preço real da Travelpayouts. Marque 'Sempre cruzar com "
            "pesquisa web (IA)' para também buscar hipóteses."
        )

    # ── Demonstração: só quando não há absolutamente nenhuma fonte ────────────
    if not results:
        _LAST_PROVIDER_DIAGNOSTIC.update(
            provider="demo",
            status="demo_no_token",
            message="Sem fonte real nem IA com resultado; modo demonstração.",
        )
        results.extend(_demo_results(search_params))

    # ── Tolerancia de datas (controlada pelo usuario) ────────────────────────
    # Preco de passagem varia bastante de um dia para o outro. Quando o
    # usuario aceita ver datas vizinhas, varremos +/- N dias reais na
    # Travelpayouts e somamos ao resultado — marcado para a UI nunca disfarçar
    # que aquela tarifa e de outro dia.
    flex_days = int(search_params.get("date_flex_days") or 0)
    # Otimizacao: flex_days >= 14 ("mes inteiro") — o search_flights da
    # Travelpayouts ja fez uma busca por mes inteiro internamente como passo 2
    # (month_fallback), entao nao ha ganho em fazer mais 30 chamadas dia a dia;
    # so executa o loop de datas quando a janela e pequena (< 14 dias).
    if not is_segment and 0 < flex_days < 14 and provider.is_configured():
        try:
            flex_results = provider.search_flexible_dates(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=search_params.get("return_date"),
                flex_days=flex_days,
                currency=search_params.get("currency", "BRL"),
                limit_per_day=10,
            )
            if flex_results:
                results.extend(flex_results)
                _LAST_PROVIDER_DIAGNOSTIC["date_flex"] = (
                    f"{len(flex_results)} cotacao(oes) extras em datas vizinhas "
                    f"(+/- {flex_days} dia(s))."
                )
        except TravelPayoutsProviderError:
            pass

    direct_results = _sort_and_dedupe(results)

    # ── Multi-segment search via hubs nacionais e internacionais ─────────────
    # max_connection_hubs e controlado pelo usuario: mais hubs == mais chance
    # de achar a combinacao mais barata (o ranking em
    # air_network.find_candidate_hubs ja devolve um leque diverso de
    # aeroportos — nacionais para rotas domesticas/chegando ao Brasil, e
    # grandes hubs internacionais (Lisboa, Madri, Miami...) para quem sai do
    # Brasil rumo ao exterior, onde o voo direto costuma ser caro/raro).
    # 0 desativa a busca.
    max_hubs = int(search_params.get("max_connection_hubs", 4) or 0)
    combined: list[dict[str, Any]] = []
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

    # ── Marcador honesto de cobertura ─────────────────────────────────────────
    # Roda por ultimo (depois das rotas combinadas) — uma conexao via hub
    # tambem e cobertura real (precos vindos da Travelpayouts), entao marcar
    # "sem cobertura" antes dela existir gerava um aviso falso de "nada
    # encontrado" mesmo quando a busca multi-trecho ja tinha achado algo.
    if not _has_real_results(direct_results):
        _LAST_PROVIDER_DIAGNOSTIC["coverage"] = "sem_cobertura_real"
        _LAST_PROVIDER_DIAGNOSTIC["coverage_note"] = (
            "Nenhuma fonte de preço publicado (Travelpayouts/conexões validadas) tem "
            "dados para esta rota/data. Resultados de Gemini/OpenAI, quando presentes, "
            "são apenas hipóteses não validadas."
        )
    else:
        _LAST_PROVIDER_DIAGNOSTIC["coverage"] = "ok"

    # Cada oferta sai carimbada com a confiabilidade da fonte, para o ranking e
    # a UI tratarem preço real e hipótese de IA de formas diferentes.
    for offer in direct_results:
        offer["source_confidence"] = _source_confidence(offer)

    return direct_results


def _source_confidence(offer: dict[str, Any]) -> str:
    """Classifica a confiabilidade da origem do preço:
    - "real": preço publicado (Travelpayouts e conexões montadas a partir dele);
    - "unverified": hipótese de IA de busca web (Gemini/OpenAI) — não validada;
    - "demo": dado ilustrativo de demonstração."""
    src = str(offer.get("provider") or offer.get("source") or "").lower()
    if any(m in src for m in ("demo", "mock", "fallback")):
        return "demo"
    if "travelpayouts" in src or "combinado" in src:
        return "real"
    return "unverified"


def _search_segment(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Search a single one-way segment.  Used by multi_segment_search as the
    provider function for each leg — never triggers multi-segment recursion.
    """
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
    # Uma rota combinada só pode ser montada com pernas reais. Dados demo não
    # representam voos compatíveis entre si e jamais devem virar conexão.
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
            return _sort_and_dedupe(_demo_year_results(search_params))
    return _sort_and_dedupe(_demo_year_results(search_params))


def get_last_provider_diagnostic() -> dict[str, Any]:
    return dict(_LAST_PROVIDER_DIAGNOSTIC)


def _sort_and_dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple, dict[str, Any]] = {}
    for item in results:
        # Itinerario impossivel (volta antes ou no mesmo dia da ida): o cache
        # da Travelpayouts as vezes pareia datas de registros diferentes.
        # Nunca exibir datas invertidas — descarta a volta invalida.
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
