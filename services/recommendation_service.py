"""Ranks flight options for the comparator-style results screen.

Pure-Python (no Streamlit, no DB): given the offers returned by the search
providers and the user's stated preferences, picks a "Recomendado", a
"Mais barato" and a "Mais rápido" option, sorts the full list, and explains the
headline pick in one short sentence.
"""
from __future__ import annotations

from typing import Any

from services.miles_service import DEFAULT_CENTS_PER_MILE, compare_cash_vs_miles, estimate_miles_from_cash_price


def _price(option: dict) -> float:
    try:
        return float(option.get("price_brl") or option.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def _duration(option: dict) -> float:
    try:
        return float(option.get("duration_minutes") or 0)
    except (TypeError, ValueError):
        return 0.0


def _stops(option: dict) -> int:
    try:
        return int(option.get("stops") or 0)
    except (TypeError, ValueError):
        return 0


def _mile_value(option: dict, min_mile_value: float) -> float:
    miles = option.get("estimated_miles") or estimate_miles_from_cash_price(_price(option), min_mile_value)
    cmp = compare_cash_vs_miles(_price(option), miles, option.get("taxes") or 0.0, min_mile_value)
    return float(cmp.get("mile_value") or 0.0)


def _recommendation_score(option: dict, prefs: dict, cheapest_price: float, fastest_duration: float) -> float:
    """Lower is better — blends price, duration and stops against the user's
    stated limits so 'Recomendados' favours the best overall trade-off, not just
    the cheapest fare."""
    price = _price(option)
    duration = _duration(option)
    stops = _stops(option)

    price_ratio = (price / cheapest_price) if cheapest_price > 0 else 1.0
    duration_ratio = (duration / fastest_duration) if fastest_duration > 0 else 1.0

    score = price_ratio * 0.55 + duration_ratio * 0.30 + (stops * 0.05)

    max_price = prefs.get("max_price")
    if max_price and price > float(max_price):
        score += 0.5
    max_stops = prefs.get("max_stops")
    if max_stops is not None and stops > int(max_stops):
        score += 0.3
    max_duration = prefs.get("max_duration_minutes")
    if max_duration and duration > float(max_duration):
        score += 0.3

    # Confiabilidade da fonte: um preço real da Travelpayouts deve liderar sobre
    # uma hipótese de IA não validada de valor parecido; dado de demonstração
    # nunca encabeça a lista.
    confidence = str(option.get("source_confidence") or "").lower()
    if confidence == "unverified":
        score += 0.40
    elif confidence == "demo":
        score += 1.0

    # Risco de conexão: bilhetes separados (compra em 2 fontes, sem proteção de
    # conexão) e trocas de companhia carregam risco real de perder o voo.
    if option.get("separate_ticket"):
        score += 0.30
    if option.get("connection_risk") == "alto":
        score += 0.30
    return score


def rank_flight_options(options: list[dict], user_preferences: dict | None = None) -> dict:
    """Rank flight options and pick the headline cards for the results screen.

    ``user_preferences`` may include ``max_price``, ``max_stops``,
    ``max_duration_minutes``, ``min_mile_value``, ``sort_by`` (one of
    "recomendados" | "menor_preco" | "menor_duracao" | "menos_conexoes" |
    "melhor_milhas").

    Returns ``{"recommended_option", "cheapest_option", "fastest_option",
    "sorted_options", "reason"}``. All values are ``None``/``[]`` when
    ``options`` is empty.
    """
    prefs = user_preferences or {}
    valid = [o for o in (options or []) if _price(o) > 0]
    if not valid:
        return {
            "recommended_option": None,
            "cheapest_option": None,
            "fastest_option": None,
            "sorted_options": [],
            "reason": "Nenhuma tarifa encontrada para esta busca.",
        }

    cheapest_option = min(valid, key=_price)
    fastest_option = min((o for o in valid if _duration(o) > 0), key=_duration, default=cheapest_option)

    cheapest_price = _price(cheapest_option)
    fastest_duration = _duration(fastest_option) or 1.0

    recommended_option = min(
        valid, key=lambda o: _recommendation_score(o, prefs, cheapest_price, fastest_duration)
    )

    sort_by = (prefs.get("sort_by") or "recomendados").lower()
    min_mile_value = float(prefs.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)
    if sort_by == "menor_preco":
        sorted_options = sorted(valid, key=_price)
    elif sort_by == "menor_duracao":
        sorted_options = sorted(valid, key=_duration)
    elif sort_by == "menos_conexoes":
        sorted_options = sorted(valid, key=lambda o: (_stops(o), _price(o)))
    elif sort_by == "melhor_milhas":
        sorted_options = sorted(valid, key=lambda o: -_mile_value(o, min_mile_value))
    else:
        sorted_options = sorted(
            valid, key=lambda o: _recommendation_score(o, prefs, cheapest_price, fastest_duration)
        )

    reason = _build_reason(recommended_option, cheapest_option, fastest_option, prefs)

    return {
        "recommended_option": recommended_option,
        "cheapest_option": cheapest_option,
        "fastest_option": fastest_option,
        "sorted_options": sorted_options,
        "reason": reason,
    }


def _build_reason(recommended: dict, cheapest: dict, fastest: dict, prefs: dict) -> str:
    if recommended is cheapest and recommended is fastest:
        return "Menor preço e menor duração — a melhor combinação encontrada."
    if recommended is cheapest:
        return "Melhor preço entre as opções com bom equilíbrio de duração e conexões."
    if recommended is fastest:
        return "Chega mais rápido com um preço competitivo dentro das suas preferências."
    stops = _stops(recommended)
    stops_label = "voo direto" if stops == 0 else f"{stops} conexão(ões)"
    return f"Bom equilíbrio entre preço, duração e conexões ({stops_label})."
