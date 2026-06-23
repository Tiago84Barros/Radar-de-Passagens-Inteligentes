"""Decision engine — turns raw quotes into a buy / monitor / wait recommendation.

This is the heart of the "radar de decisão" refactor: instead of charting the
past, it answers *should I buy now, monitor, or redeem miles?* for a route or a
found destination.

It is a pure-Python service (no Streamlit, no DB) so it is easy to unit-test and
reuse from both the UI (Home tab) and the alert pipeline. It consumes quotes
already produced by the preserved search engine
(``providers.provider_manager.search_all_providers`` → enriched via
``services.opportunity_service`` / ``services.multi_destination_adapter``).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from services.miles_service import (
    DEFAULT_CENTS_PER_MILE,
    compare_cash_vs_miles,
    estimate_miles_from_cash_price,
)

# Recommendation labels (also used by the UI and alerts). Keep in sync with spec.
REC_BUY = "Comprar agora"
REC_MONITOR = "Monitorar"
REC_WAIT = "Aguardar"
REC_CASH = "Melhor pagar em dinheiro"
REC_MILES = "Melhor usar milhas"
REC_IGNORE = "Ignorar"
REC_COMMON = "Preço comum"


def _price(quote: dict) -> float:
    try:
        return float(quote.get("price_brl") or quote.get("preço") or 0)
    except (TypeError, ValueError):
        return 0.0


def _valid_quotes(quotes: Iterable[dict]) -> list[dict]:
    return [q for q in (quotes or []) if _price(q) > 0]


def _days_until(value: Any) -> int | None:
    """Days from today until a departure date (None when unknown)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        try:
            import pandas as pd

            parsed = pd.to_datetime(value, errors="coerce")
            if parsed is None or pd.isna(parsed):
                return None
            value = parsed.date()
        except Exception:
            return None
    return (value - date.today()).days


def _miles_for(quote: dict, mile_value_brl: float) -> tuple[int, float]:
    """Return (miles_required, taxes) for a quote.

    Uses real award fields when present (``miles_required`` / ``taxes``);
    otherwise estimates miles from the cash price."""
    miles_offer = quote.get("miles_offer") or {}
    miles = quote.get("miles_required") or miles_offer.get("amount") or quote.get("estimated_miles")
    if not miles:
        miles = estimate_miles_from_cash_price(_price(quote), mile_value_brl)
    taxes = float(
        quote.get("taxes")
        or quote.get("award_taxes")
        or miles_offer.get("taxes_brl")
        or 0.0
    )
    return int(miles or 0), taxes


def _has_verified_miles(quote: dict) -> bool:
    miles_offer = quote.get("miles_offer") or {}
    return bool(quote.get("miles_required") or miles_offer.get("amount"))


def build_purchase_recommendation(
    quotes: list[dict],
    search_params: dict | None = None,
    recent_history: dict | None = None,
    user_rules: dict | None = None,
) -> dict:
    """Build a structured purchase recommendation from a set of quotes.

    Parameters
    ----------
    quotes
        Deals for a single route or destination, each a dict with at least
        ``price_brl`` (or ``preço``). Optional: ``score``, ``estimated_miles``,
        ``miles_required``, ``taxes``, ``departure_date``, ``stops``,
        ``duration_minutes``, ``airline``, ``provider``.
    search_params
        User search context: ``max_price``, ``consider_miles`` (bool),
        ``user_min_mile_value``, ``departure_date``.
    recent_history
        Optional short-window stats from the DB: ``recent_min``, ``recent_avg``,
        ``sample_size``. Used only as supporting evidence, never as the headline.
    user_rules
        Optional overrides: ``max_price``, ``min_mile_value``, ``max_stops``,
        ``max_duration_minutes``.

    Returns the dict described in the product spec (recommendation, confidence,
    main_reason, supporting_reasons, best_cash_option, best_miles_option,
    best_overall_option, should_alert).
    """
    search_params = search_params or {}
    user_rules = user_rules or {}
    recent_history = recent_history or {}

    max_price = _coalesce_float(user_rules.get("max_price"), search_params.get("max_price"))
    consider_miles = bool(search_params.get("consider_miles", True))
    min_mile_value = _coalesce_float(
        user_rules.get("min_mile_value"),
        search_params.get("user_min_mile_value"),
        DEFAULT_CENTS_PER_MILE,
    )

    valid = _valid_quotes(quotes)
    if not valid:
        return {
            "recommendation": REC_WAIT,
            "confidence": 20,
            "main_reason": "Nenhuma tarifa disponível para avaliar agora.",
            "supporting_reasons": [
                "O radar ainda não coletou preços para esta busca.",
                "Clique em Buscar agora ou ative o monitoramento da rota.",
            ],
            "best_cash_option": None,
            "best_miles_option": None,
            "best_overall_option": None,
            "should_alert": False,
        }

    # ── Best options ──────────────────────────────────────────────────────────
    best_cash = min(valid, key=_price)
    best_price = _price(best_cash)

    # Best miles option: highest implied mile value (most value per mile).
    miles_evaluated = []
    for q in valid:
        miles, taxes = _miles_for(q, min_mile_value)
        cmp = compare_cash_vs_miles(_price(q), miles, taxes, min_mile_value)
        miles_evaluated.append((q, cmp))
    best_miles_q, best_miles_cmp = max(
        miles_evaluated, key=lambda pair: pair[1]["mile_value"]
    )

    best_cash_option = _as_option(best_cash, min_mile_value)
    best_miles_option = _as_option(best_miles_q, min_mile_value, miles_cmp=best_miles_cmp)

    # ── Evidence ──────────────────────────────────────────────────────────────
    reasons: list[str] = []
    confidence = 50
    score = int(best_cash.get("score") or 0)

    below_budget = max_price is not None and best_price <= max_price
    if below_budget:
        reasons.append(
            f"Preço R$ {best_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            + f" está dentro do seu limite."
        )
        confidence += 12

    # Short recent history (supporting only — never the protagonist).
    recent_min = _coalesce_float(recent_history.get("recent_min"))
    recent_avg = _coalesce_float(recent_history.get("recent_avg"))
    pct_below_avg = None
    if recent_avg and recent_avg > 0:
        pct_below_avg = (recent_avg - best_price) / recent_avg * 100.0
        if pct_below_avg >= 5:
            reasons.append(
                f"Está {pct_below_avg:.0f}% abaixo da média recente observada pelo radar."
            )
            confidence += min(int(pct_below_avg), 20)
        elif pct_below_avg <= -5:
            reasons.append(
                f"Está {abs(pct_below_avg):.0f}% acima da média recente — pode cair."
            )
            confidence -= 10
    at_or_below_recent_min = bool(recent_min and best_price <= recent_min * 1.01)
    if at_or_below_recent_min:
        reasons.append("É o menor preço recente já visto para esta busca.")
        confidence += 12

    days = _days_until(search_params.get("departure_date") or best_cash.get("departure_date"))
    if days is not None:
        if days <= 21:
            reasons.append(f"Faltam só {days} dias para a viagem — tende a subir.")
            confidence += 6
        elif days >= 120:
            reasons.append(f"Ainda faltam {days} dias — há tempo para monitorar.")

    if score:
        reasons.append(f"Score do radar: {score}/100.")
        confidence += int((score - 50) / 5)

    # Cash vs miles verdict for the cheapest option.
    cash_vs_miles = compare_cash_vs_miles(
        best_price, *_miles_for(best_cash, min_mile_value), min_mile_value
    )
    # Estimar milhas a partir do preço cash é útil como referência visual, mas
    # não prova disponibilidade nem custo de emissão. Só uma oferta concreta do
    # programa pode sustentar a recomendação "Melhor usar milhas".
    miles_worth = consider_miles and _has_verified_miles(best_cash) and cash_vs_miles["worth_miles"]

    # ── Headline recommendation ───────────────────────────────────────────────
    strong_buy = (below_budget and (at_or_below_recent_min or (pct_below_avg or 0) >= 12)) or score >= 80
    soft_buy = below_budget or score >= 70

    if miles_worth and (strong_buy or soft_buy):
        recommendation = REC_MILES
        main_reason = cash_vs_miles["reason"]
        confidence += 8
    elif strong_buy:
        recommendation = REC_BUY
        main_reason = (
            "Preço dentro do limite e abaixo do padrão recente — boa hora para comprar."
            if below_budget else "Score alto e preço competitivo — boa hora para comprar."
        )
    elif soft_buy:
        recommendation = REC_BUY if below_budget else REC_MONITOR
        main_reason = (
            "Preço dentro do seu limite — vale comprar ou travar agora."
            if below_budget else "Preço razoável; monitore para confirmar a tendência."
        )
    elif max_price is not None and best_price > max_price:
        recommendation = REC_MONITOR
        main_reason = (
            "Acima do seu preço máximo. Monitore — o radar avisa quando cair."
        )
        confidence -= 6
    else:
        recommendation = REC_MONITOR if (pct_below_avg or 0) > -5 else REC_WAIT
        main_reason = "Preço comum para esta rota; vale monitorar antes de comprar."

    if miles_worth and recommendation != REC_MILES:
        reasons.append(cash_vs_miles["reason"])

    # best_overall: miles when clearly better, else cheapest cash.
    best_overall_option = best_miles_option if recommendation == REC_MILES else best_cash_option

    confidence = max(5, min(99, confidence))

    should_alert = bool(
        (max_price is not None and best_price <= max_price)
        or recommendation in {REC_BUY, REC_MILES}
        or score >= 70
    )

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "main_reason": main_reason,
        "supporting_reasons": reasons,
        "best_cash_option": best_cash_option,
        "best_miles_option": best_miles_option,
        "best_overall_option": best_overall_option,
        "cash_vs_miles": cash_vs_miles,
        "should_alert": should_alert,
    }


def _as_option(quote: dict, mile_value_brl: float, miles_cmp: dict | None = None) -> dict:
    miles, taxes = _miles_for(quote, mile_value_brl)
    cmp = miles_cmp or compare_cash_vs_miles(_price(quote), miles, taxes, mile_value_brl)
    return {
        "price_brl": _price(quote),
        "airline": quote.get("airline") or "",
        "provider": quote.get("provider") or quote.get("source") or "",
        "estimated_miles": miles,
        "mile_value": cmp["mile_value"],
        "miles_estimated": not _has_verified_miles(quote),
        "taxes": taxes,
        "stops": quote.get("stops"),
        "duration_minutes": quote.get("duration_minutes"),
        "departure_date": quote.get("departure_date"),
        "return_date": quote.get("return_date"),
        "score": int(quote.get("score") or 0),
        "booking_link": quote.get("booking_link") or quote.get("link") or "",
        "origin_iata": quote.get("origin_iata") or quote.get("origem") or "",
        "destination_iata": quote.get("destination_iata") or quote.get("destino") or "",
    }


def _coalesce_float(*values) -> float | None:
    for v in values:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None
