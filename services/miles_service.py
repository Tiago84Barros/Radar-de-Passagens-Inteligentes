from __future__ import annotations

# Default estimated value per mile in BRL (R$ 0,035 = 3,5 centavos por milha)
DEFAULT_CENTS_PER_MILE: float = 0.035

# Shown wherever estimated miles appear. Required by spec: there is no real
# miles-availability API, so every miles figure is an estimate.
MILES_DISCLAIMER: str = (
    "Milhas estimadas. A disponibilidade real depende do programa de fidelidade."
)


def estimate_miles(price_brl: float, cents_per_mile: float = DEFAULT_CENTS_PER_MILE) -> int:
    """
    Estimate miles needed to redeem a ticket at the given price.
    Formula: miles = price_brl / cents_per_mile
    Default: R$ 0,035 per mile → R$ 700 = 20.000 miles
    """
    if price_brl <= 0 or cents_per_mile <= 0:
        return 0
    return int(round(price_brl / cents_per_mile / 500) * 500)  # round to nearest 500


# Spec alias: explicit name used by the decision engine and adapters.
def estimate_miles_from_cash_price(
    price_brl: float, mile_value_brl: float = DEFAULT_CENTS_PER_MILE
) -> int:
    """Estimate the miles an emission would cost, from the cash price.

    ``mile_value_brl`` is the assumed value of one mile in reais (default R$ 0,035).
    Thin wrapper over :func:`estimate_miles` kept as the spec's public name."""
    return estimate_miles(price_brl, mile_value_brl)


def calculate_mile_value(cash_price: float, miles_required: float, taxes: float = 0.0) -> float:
    """Implied value of one mile, in reais, for a concrete redemption.

    valor_por_milha = (preço em dinheiro − taxas da emissão) / milhas necessárias

    The cash you avoid paying is the fare minus the taxes you still pay on the
    award ticket. Returns 0.0 when miles are missing/invalid."""
    try:
        cash = float(cash_price)
        miles = float(miles_required)
        fees = float(taxes or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if miles <= 0:
        return 0.0
    saved = cash - fees
    if saved <= 0:
        return 0.0
    return round(saved / miles, 5)


def compare_cash_vs_miles(
    cash_price: float,
    miles_required: float,
    taxes: float = 0.0,
    user_min_mile_value: float = DEFAULT_CENTS_PER_MILE,
) -> dict:
    """Compare paying in cash vs redeeming miles for the same ticket.

    Returns a structured verdict the decision engine consumes:
        {
          "mile_value": R$ por milha implícito,
          "user_min_mile_value": piso aceitável do usuário,
          "worth_miles": bool,                # vale emitir com milhas?
          "recommendation": "Melhor usar milhas" | "Melhor pagar em dinheiro" | "Indiferente",
          "cash_price": ...,
          "miles_required": ...,
          "taxes": ...,
          "reason": texto curto em pt-BR,
        }

    Example (spec): R$ 1.500 vs 25.000 milhas + R$ 150 de taxas →
    valor por milha = (1500−150)/25000 = R$ 0,054 ≥ 0,035 → "Melhor usar milhas".
    """
    mile_value = calculate_mile_value(cash_price, miles_required, taxes)
    floor = float(user_min_mile_value or DEFAULT_CENTS_PER_MILE)

    has_miles = float(miles_required or 0) > 0 and mile_value > 0
    worth_miles = has_miles and mile_value >= floor

    if not has_miles:
        recommendation = "Melhor pagar em dinheiro"
        reason = "Sem dados de emissão em milhas para esta opção."
    elif worth_miles:
        recommendation = "Melhor usar milhas"
        reason = (
            f"Cada milha vale R$ {mile_value:.3f}".replace(".", ",")
            + f", acima do seu mínimo de {cents_per_mile_label(floor)}."
        )
    else:
        recommendation = "Melhor pagar em dinheiro"
        reason = (
            f"Cada milha vale só R$ {mile_value:.3f}".replace(".", ",")
            + f", abaixo do seu mínimo de {cents_per_mile_label(floor)}."
        )

    return {
        "mile_value": mile_value,
        "user_min_mile_value": floor,
        "worth_miles": worth_miles,
        "recommendation": recommendation,
        "cash_price": float(cash_price or 0),
        "miles_required": float(miles_required or 0),
        "taxes": float(taxes or 0),
        "reason": reason,
    }


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
