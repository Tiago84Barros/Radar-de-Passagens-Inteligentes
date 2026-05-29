from __future__ import annotations

# Default estimated value per mile in BRL (R$ 0,035 = 3,5 centavos por milha)
DEFAULT_CENTS_PER_MILE: float = 0.035


def estimate_miles(price_brl: float, cents_per_mile: float = DEFAULT_CENTS_PER_MILE) -> int:
    """
    Estimate miles needed to redeem a ticket at the given price.
    Formula: miles = price_brl / cents_per_mile
    Default: R$ 0,035 per mile → R$ 700 = 20.000 miles
    """
    if price_brl <= 0 or cents_per_mile <= 0:
        return 0
    return int(round(price_brl / cents_per_mile / 500) * 500)  # round to nearest 500


def format_miles(miles: int) -> str:
    """Format miles in Brazilian style: 18.500 milhas."""
    if not miles:
        return "–"
    return f"{miles:,}".replace(",", ".") + " milhas"


def cents_per_mile_label(cents: float) -> str:
    """Format cents per mile as R$ 0,035."""
    return f"R$ {cents:.3f}".replace(".", ",")


def miles_score(price_brl: float, miles: int, cents_per_mile: float = DEFAULT_CENTS_PER_MILE) -> int:
    """
    Score the miles efficiency of a deal (0–100).
    Higher score = better value per mile.
    """
    if miles <= 0 or price_brl <= 0:
        return 0
    actual_cpp = price_brl / miles
    if actual_cpp <= cents_per_mile * 0.5:
        return 100
    if actual_cpp >= cents_per_mile * 2:
        return 0
    ratio = (cents_per_mile * 2 - actual_cpp) / (cents_per_mile * 1.5)
    return int(min(max(ratio * 100, 0), 100))


def enrich_deal_with_miles(deal: dict, cents_per_mile: float = DEFAULT_CENTS_PER_MILE) -> dict:
    """Add miles estimation fields to a deal dict."""
    price = float(deal.get("price_brl") or deal.get("preço") or 0)
    miles = estimate_miles(price, cents_per_mile)
    return {
        **deal,
        "estimated_miles": miles,
        "miles_formatted": format_miles(miles),
        "cents_per_mile": cents_per_mile,
        "miles_score": miles_score(price, miles, cents_per_mile),
    }
