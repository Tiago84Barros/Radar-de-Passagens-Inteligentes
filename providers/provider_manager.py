"""Orquestra a busca de tarifas usando exclusivamente as APIs configuradas.

Scraping desativado. O app usa somente APIs configuradas.

Papeis bem definidos:
- Travelpayouts = fonte de precos reais (provider primario).
- Gemini = apoio de analise/organizacao/fallback via busca web — nunca fonte
  primaria de tarifa real; so entra quando a Travelpayouts nao retorna nada.
"""
from __future__ import annotations

from datetime import date
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
    """True for published API prices or web fares backed by native citations."""
    for r in results:
        src = str(r.get("provider") or r.get("source") or "").lower()
        if any(m in src for m in ("demo", "mock", "fallback")):
            continue
        if "travelpayouts" in src or "combinado" in src or r.get("source_verified") is True:
            return True
    return False


def _confirmed_web_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Defense in depth: never merge an AI fare without its cited source."""
    return [
        item
        for item in results
        if item.get("source_verified") is True
        and bool(item.get("source_url"))
        and bool(item.get("booking_link"))
    ]


def search_all_providers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Hierarquia de confiabilidade: a TRAVELPAYOUTS (preço real, não alucina) é a
    fonte PRIMÁRIA. As IAs de busca web (Gemini/OpenAI) só entram com uma URL
    de fonte presente nas citações nativas da ferramenta de busca
    quando não há preço real para a rota/data — ou quando o usuário marca
    ``force_web_search``. Respostas sem citação são descartadas. Inclui conexões
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
            tp_results = _filter_to_requested_dates(tp_results, search_params)
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

    # ── IA (Gemini/OpenAI) — só entram tarifas com fonte citada ───────────────
    # Roda quando não há preço real (cobre rotas de nicho/datas distantes que a
    # Travelpayouts não tem) ou quando o usuário força a busca web.
    if force_web or not has_real:
        gemini_results, gemini_msg = _search_gemini(search_params)
        gemini_results = _filter_to_requested_dates(_confirmed_web_results(gemini_results), search_params)
        results.extend(gemini_results)
        if gemini_results:
            _LAST_PROVIDER_DIAGNOSTIC["gemini"] = (
                f"{len(gemini_results)} tarifa(s) via Gemini com fonte citada."
            )
            if not has_real:
                _LAST_PROVIDER_DIAGNOSTIC.update(
                    provider="gemini_web_search",
                    status="confirmed_web_ok",
                    message=f"{len(gemini_results)} tarifa(s) via Gemini com fonte confirmada.",
                )
        elif gemini_msg != "nao_configurado":
            _LAST_PROVIDER_DIAGNOSTIC["gemini"] = gemini_msg

        openai_results, openai_msg = _search_openai(search_params)
        openai_results = _filter_to_requested_dates(_confirmed_web_results(openai_results), search_params)
        results.extend(openai_results)
        if openai_results:
            _LAST_PROVIDER_DIAGNOSTIC["openai"] = (
                f"{len(openai_results)} tarifa(s) via OpenAI com fonte citada."
            )
        elif openai_msg != "nao_configurado":
            _LAST_PROVIDER_DIAGNOSTIC["openai"] = openai_msg
    else:
        _LAST_PROVIDER_DIAGNOSTIC["ai_skipped"] = (
            "IA não consultada: há preço real da Travelpayouts. Marque 'Sempre cruzar com "
            "pesquisa web (IA)' para também buscar fontes citadas."
        )

    # Nunca gere passagens de demonstração. Ausência de fonte confirmada deve
    # aparecer como ausência de resultado, não como uma tarifa plausível.
    if not results:
        _LAST_PROVIDER_DIAGNOSTIC.update(
            provider="none",
            status="no_confirmed_source",
            message="Nenhuma tarifa com fonte confirmada foi encontrada.",
        )

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
            flex_results = _filter_to_requested_dates(flex_results, search_params)
            if flex_results:
                results.extend(flex_results)
                _LAST_PROVIDER_DIAGNOSTIC["date_flex"] = (
                    f"{len(flex_results)} cotacao(oes) extras em datas vizinhas "
                    f"(+/- {flex_days} dia(s))."
                )
        except TravelPayoutsProviderError:
            pass

    direct_results = _sort_and_dedupe(_filter_to_requested_dates(results, search_params))

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
                direct_results = _sort_and_dedupe(_filter_to_requested_dates(direct_results + combined, search_params))
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
            "Nenhuma fonte de preço publicado ou página citada por Gemini/OpenAI "
            "confirmou tarifa para esta rota/data."
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
    - "verified": tarifa de busca web vinculada a uma citação nativa;
    - "demo": dado ilustrativo de demonstração."""
    src = str(offer.get("provider") or offer.get("source") or "").lower()
    if any(m in src for m in ("demo", "mock", "fallback")):
        return "demo"
    if "travelpayouts" in src or "combinado" in src:
        return "real"
    if offer.get("source_verified") is True and offer.get("source_url"):
        return "verified"
    return "unverified"


def _search_segment(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Search a single one-way segment.  Used by multi_segment_search as the
    provider function for each leg — never triggers multi-segment recursion.
    """
    provider = TravelPayoutsProvider()
    if provider.is_configured():
        try:
            segment_results = provider.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=None,   # segments are always one-way
                currency=search_params.get("currency", "BRL"),
                limit=search_params.get("limit", 5),
            )
            return _filter_to_requested_dates(segment_results, search_params)
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
            return []
    return []


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


def _filter_to_requested_dates(results: list[dict[str, Any]], search_params: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep only fares inside the user-approved date window.

    Travelpayouts can return the cheapest cached fare for the whole month when
    the exact day has no cache. That is useful only after this guard confirms
    the real fare date matches the user's tolerance.
    """
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
