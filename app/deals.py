from __future__ import annotations

from statistics import mean
from typing import Any


def calculate_deal_score(quote: Any, max_price: float | None = None, historical_quotes: list[Any] | None = None) -> dict:
    price = _get_price(quote)
    if price <= 0:
        return {"score": 0, "classification": "Normal", "is_opportunity": False, "economy": 0.0}

    score = 35
    economy = 0.0
    if max_price:
        economy = max(float(max_price) - price, 0.0)
        if price <= max_price:
            score += 30
            discount = economy / float(max_price)
            score += min(int(discount * 40), 25)

    historical_prices = [_get_price(item) for item in (historical_quotes or [])]
    historical_prices = [item for item in historical_prices if item > 0]
    if historical_prices:
        avg_price = mean(historical_prices)
        if price < min(historical_prices):
            score += 15
        if avg_price and price < avg_price:
            score += min(int(((avg_price - price) / avg_price) * 30), 15)

    score = max(0, min(score, 100))
    if score >= 85:
        classification = "Excelente oportunidade"
    elif score >= 70:
        classification = "Ótima oportunidade"
    elif score >= 55:
        classification = "Boa oportunidade"
    else:
        classification = "Normal"

    return {
        "score": score,
        "classification": classification,
        "is_opportunity": classification != "Normal",
        "economy": economy,
    }


def _get_price(quote: Any) -> float:
    if isinstance(quote, dict):
        return float(quote.get("price") or 0)
    return float(getattr(quote, "price", 0) or 0)
