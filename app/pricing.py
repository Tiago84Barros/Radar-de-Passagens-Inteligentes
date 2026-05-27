from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from app.db import FlightQuote, FlightSearch


@dataclass(frozen=True)
class PriceDecision:
    should_alert: bool
    opportunity: str
    reasons: list[str]
    discount_vs_limit: float
    drop_vs_average: float | None
    is_historical_low: bool


def classify_opportunity(price: float, max_price: float, drop_vs_average: float | None, is_historical_low: bool) -> str:
    discount = ((max_price - price) / max_price) * 100 if max_price else 0
    if is_historical_low and (drop_vs_average or 0) >= 20:
        return "oportunidade_rara"
    if discount >= 25 or (drop_vs_average or 0) >= 18:
        return "excelente_oportunidade"
    if discount >= 10 or (drop_vs_average or 0) >= 10:
        return "boa_oportunidade"
    return "normal"


def evaluate_quote(search: FlightSearch, quote_price: float, history: list[FlightQuote]) -> PriceDecision:
    reasons: list[str] = []
    should_alert = False
    discount_vs_limit = ((search.max_price - quote_price) / search.max_price) * 100

    if quote_price <= search.max_price:
        should_alert = True
        reasons.append(f"Preço abaixo do limite definido ({discount_vs_limit:.1f}% de folga).")

    historical_prices = [quote.price for quote in history if quote.price > 0]
    historical_average = mean(historical_prices) if historical_prices else None
    drop_vs_average = None
    if historical_average:
        drop_vs_average = ((historical_average - quote_price) / historical_average) * 100
        if drop_vs_average >= 12:
            should_alert = True
            reasons.append(f"Queda de {drop_vs_average:.1f}% contra a média histórica recente.")

    is_historical_low = bool(historical_prices) and quote_price < min(historical_prices)
    if is_historical_low:
        should_alert = True
        reasons.append("Menor preço histórico já registrado para esta busca.")

    opportunity = classify_opportunity(quote_price, search.max_price, drop_vs_average, is_historical_low)
    if opportunity == "oportunidade_rara":
        reasons.append("Oportunidade rara: menor histórico com queda relevante contra a média.")

    return PriceDecision(
        should_alert=should_alert,
        opportunity=opportunity,
        reasons=reasons or ["Cotação registrada sem gatilho de alerta."],
        discount_vs_limit=discount_vs_limit,
        drop_vs_average=drop_vs_average,
        is_historical_low=is_historical_low,
    )
