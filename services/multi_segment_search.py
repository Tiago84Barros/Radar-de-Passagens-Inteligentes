from __future__ import annotations

"""
Multi-segment route search across the Brazilian air network.

Given origin A and destination B, this module:
  1. Identifies candidate hub airports C (e.g. GRU, BSB)
  2. Searches A→C and C→B as independent one-way legs
  3. Combines the cheapest pair into a single result
  4. Returns only combined routes that are cheaper than the direct route

The caller provides a `direct_search_fn(params) -> list[dict]` so the
same logic works for both live API and demo/fallback modes.
"""

from typing import Any, Callable

from services.air_network import find_candidate_hubs, hub_route_label, is_domestic

# Minimum layover time at the connection hub (minutes)
LAYOVER_MINUTES = 90

# Maximum total duration penalty for combined vs direct routes
# (we skip combined routes that take vastly longer)
MAX_DURATION_RATIO = 2.5


def search_via_connections(
    search_params: dict[str, Any],
    direct_search_fn: Callable[[dict[str, Any]], list[dict[str, Any]]],
    max_hubs: int = 2,
    direct_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Search for 1-stop combined routes via Brazilian hubs.

    Args:
        search_params: Same dict passed to search_all_providers.
        direct_search_fn: Function that searches a single direct route.
        max_hubs: How many hub airports to try (default 2 to limit API calls).
        direct_results: Already-fetched direct results (to compare prices).

    Returns:
        List of combined-route dicts in the same format as direct results.
        Only returns routes that are cheaper than the cheapest direct result.
    """
    origin = str(search_params.get("origin") or "").upper()
    destination = str(search_params.get("destination") or "").upper()

    if not origin or not destination or origin == destination:
        return []

    # So vale tentar conexao via hub brasileiro se a rota toca o Brasil em
    # alguma ponta — origem OU destino. Limitar a "so quando a origem e
    # domestica" deixava de fora rotas como LIS->BEL, onde conectar em GRU/GIG
    # pode ser justamente a forma mais barata (ou a unica) de fechar a viagem.
    if not _route_touches_brazil(origin, destination):
        return []

    # Cheapest known direct price (for comparison)
    direct_min = _min_price(direct_results or [])

    candidate_hubs = find_candidate_hubs(origin, destination, max_hubs)
    combined_results: list[dict[str, Any]] = []

    for hub in candidate_hubs:
        leg1_results = direct_search_fn(_segment_params(search_params, origin, hub))
        if not leg1_results:
            continue

        leg2_results = direct_search_fn(_segment_params(search_params, hub, destination))
        if not leg2_results:
            continue

        best_leg1 = min(leg1_results, key=lambda x: float(x.get("price") or 9_999_999))
        best_leg2 = min(leg2_results, key=lambda x: float(x.get("price") or 9_999_999))

        combined_price = float(best_leg1.get("price") or 0) + float(best_leg2.get("price") or 0)
        if combined_price <= 0:
            continue

        # Skip if more expensive than the cheapest direct result
        if direct_min is not None and combined_price >= direct_min:
            continue

        combined = _merge_segments(best_leg1, best_leg2, origin, destination, hub)
        combined_results.append(combined)

    return combined_results


def _segment_params(base: dict[str, Any], origin: str, destination: str) -> dict[str, Any]:
    """Build search params for a single one-way segment."""
    return {
        **base,
        "origin": origin,
        "destination": destination,
        "return_date": None,   # segments are always one-way
        "limit": 10,           # mais opcoes por trecho == mais chance de achar a tarifa mais barata
        "_is_segment": True,   # prevents recursive multi-segment calls
    }


def _merge_segments(
    leg1: dict[str, Any],
    leg2: dict[str, Any],
    origin: str,
    destination: str,
    hub: str,
) -> dict[str, Any]:
    """Combine two one-way legs into a single combined route dict."""
    price = float(leg1.get("price") or 0) + float(leg2.get("price") or 0)

    dur1 = int(leg1.get("duration_minutes") or 0)
    dur2 = int(leg2.get("duration_minutes") or 0)
    total_duration = (dur1 + LAYOVER_MINUTES + dur2) if (dur1 and dur2) else None

    airline1 = (leg1.get("airline") or "").strip()
    airline2 = (leg2.get("airline") or "").strip()
    if airline1 and airline2 and airline1 != airline2:
        airline_label = f"{airline1} + {airline2}"
    else:
        airline_label = airline1 or airline2 or "–"

    provider = f"combinado:{leg1.get('provider', 'tp')}+{leg2.get('provider', 'tp')}"

    return {
        "provider": provider,
        "source": f"combinado_via_{hub}",
        "origin": origin,
        "destination": destination,
        "via_hub": hub,
        "route_label": hub_route_label(origin, hub, destination),
        "departure_date": leg1.get("departure_date"),
        "return_date": None,
        "airline": f"{airline_label} (via {hub})",
        "price": price,
        "currency": leg1.get("currency", "BRL"),
        "duration_minutes": total_duration,
        "stops": 1,
        "booking_link": leg1.get("booking_link") or "",
        "raw_payload": {
            "combined": True,
            "via_hub": hub,
            "route_label": hub_route_label(origin, hub, destination),
            "leg1_origin": origin,
            "leg1_destination": hub,
            "leg1_price": float(leg1.get("price") or 0),
            "leg1_airline": leg1.get("airline"),
            "leg1_booking": leg1.get("booking_link"),
            "leg2_origin": hub,
            "leg2_destination": destination,
            "leg2_price": float(leg2.get("price") or 0),
            "leg2_airline": leg2.get("airline"),
            "leg2_booking": leg2.get("booking_link"),
        },
    }


def _route_touches_brazil(origin: str, destination: str) -> bool:
    """True if origin and/or destination is a known Brazilian airport —
    i.e. a connection through a Brazilian hub can plausibly shorten the trip."""
    from services.air_network import get_region
    return get_region(origin) is not None or get_region(destination) is not None


def _min_price(results: list[dict[str, Any]]) -> float | None:
    prices = [float(r.get("price") or 0) for r in results if r.get("price")]
    return min(prices) if prices else None


def summarize_segment_savings(
    combined_price: float,
    direct_price: float,
) -> str:
    """Human-readable savings label for a combined route vs direct."""
    if direct_price <= 0:
        return ""
    saving = direct_price - combined_price
    pct = (saving / direct_price) * 100
    if saving <= 0:
        return ""
    return f"R$ {saving:,.2f} mais barato que o trecho direto ({pct:.0f}%)".replace(",", "X").replace(".", ",").replace("X", ".")
