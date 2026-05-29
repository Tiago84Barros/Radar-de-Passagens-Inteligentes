from __future__ import annotations

from statistics import mean
from typing import Any


def calculate_deal_score(quote: Any, max_price: float | None = None, historical_quotes: list[Any] | None = None) -> dict:
    price = _get_price(quote)
    if price <= 0:
        return _decision(0, "Normal", False, 0.0, 0.0, False)

    score = 30
    economy = 0.0
    drop_vs_average = 0.0
    historical_low = False

    if max_price:
        economy = max(float(max_price) - price, 0.0)
        if price <= float(max_price):
            score += 30
            score += min(int((economy / float(max_price)) * 35), 20)

    historical_prices = [_get_price(item) for item in historical_quotes or []]
    historical_prices = [item for item in historical_prices if item > 0]
    if historical_prices:
        avg_price = mean(historical_prices)
        historical_low = price < min(historical_prices)
        if historical_low:
            score += 12
        if avg_price > 0 and price < avg_price:
            drop_vs_average = ((avg_price - price) / avg_price) * 100
            score += min(int(drop_vs_average), 18)

    stops = _get_number(quote, "stops")
    duration = _get_number(quote, "duration_minutes")
    source = _get_value(quote, "source") or _get_value(quote, "provider")
    if stops == 0:
        score += 5
    elif stops and stops > 1:
        score -= 5
    # Total travel time (ida + volta + conexões) as a graduated factor: short
    # trips are rewarded, very long ones penalized, so duration weighs in the score.
    if duration:
        if duration <= 180:        # até 3h
            score += 6
        elif duration <= 300:      # até 5h
            score += 3
        elif duration <= 720:      # até 12h
            score += 0
        elif duration <= 1080:     # até 18h
            score -= 4
        else:                      # mais de 18h
            score -= 8
    if source == "travelpayouts":
        score += 3

    score = max(0, min(int(score), 100))
    if score >= 85:
        classification = "Excelente oportunidade"
    elif score >= 70:
        classification = "Otima oportunidade"
    elif score >= 55:
        classification = "Boa oportunidade"
    else:
        classification = "Normal"

    is_opportunity = (
        classification != "Normal"
        or bool(max_price and price <= float(max_price))
        or drop_vs_average >= 20
    )
    return _decision(score, classification, is_opportunity, economy, drop_vs_average, historical_low)


def should_send_alert(decision: dict, quote: Any, max_price: float | None) -> bool:
    price = _get_price(quote)
    return bool(
        (max_price and price <= float(max_price))
        or int(decision.get("score") or 0) >= 70
        or float(decision.get("drop_vs_average") or 0) >= 20
    )


def _decision(
    score: int,
    classification: str,
    is_opportunity: bool,
    economy: float,
    drop_vs_average: float,
    historical_low: bool,
) -> dict:
    return {
        "score": score,
        "classification": classification,
        "is_opportunity": is_opportunity,
        "economy": economy,
        "drop_vs_average": drop_vs_average,
        "is_historical_low": historical_low,
        "reasons": [classification],
    }


def _get_price(quote: Any) -> float:
    return _get_number(quote, "price") or 0.0


def _get_number(quote: Any, key: str) -> float | None:
    value = _get_value(quote, key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_value(quote: Any, key: str) -> Any:
    if isinstance(quote, dict):
        return quote.get(key)
    return getattr(quote, key, None)
