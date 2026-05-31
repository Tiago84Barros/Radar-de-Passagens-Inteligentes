"""Geographic filter layer placed BEFORE the multi-destination search engine.

It turns the user's region/continent selection into a concrete list of candidate
destination IATAs. The preserved search engine
(``services.multi_destination_adapter.live_multi_destination_search`` /
``find_cheapest_destinations``) then receives only those candidates — its logic
is untouched; we merely narrow the input.
"""
from __future__ import annotations

from data.geography_catalog import (
    AREA_BOTH,
    AREA_BRAZIL,
    AREA_INTERNATIONAL,
    BRAZIL_REGIONS,
    INTERNATIONAL_REGIONS,
    region_for_iata,
)

# Internal scope codes used by the ranking engine / adapter.
_SCOPE_FOR_AREA = {
    AREA_BRAZIL: "nacional",
    AREA_INTERNATIONAL: "internacional",
    AREA_BOTH: "ambos",
}


def scope_for_area(area_scope: str) -> str:
    """Map the sidebar area label to the adapter's internal scope code."""
    return _SCOPE_FOR_AREA.get(area_scope, "ambos")


def get_destination_iatas_for_filters(
    area_scope: str,
    brazil_regions: list[str] | None = None,
    international_regions: list[str] | None = None,
    origin: str | None = None,
) -> list[str]:
    """Resolve the eligible destination IATAs for the selected geographic filters.

    Rules (spec §4 / §10):
      • area_scope "Brasil"  → only the selected Brazilian regions.
      • area_scope "Exterior"→ only the selected international regions.
      • area_scope "Ambos"   → both.
      • No region selected within a category → use ALL regions of that category.
      • De-duplicate, preserve logical order, never include the origin airport.
    """
    origin_code = (origin or "").upper().strip()
    codes: list[str] = []

    if area_scope in (AREA_BRAZIL, AREA_BOTH):
        regions = brazil_regions or list(BRAZIL_REGIONS.keys())
        for region in regions:
            codes.extend(BRAZIL_REGIONS.get(region, []))

    if area_scope in (AREA_INTERNATIONAL, AREA_BOTH):
        regions = international_regions or list(INTERNATIONAL_REGIONS.keys())
        for region in regions:
            codes.extend(INTERNATIONAL_REGIONS.get(region, []))

    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        c = code.upper()
        if c == origin_code or c in seen:
            continue
        seen.add(c)
        ordered.append(c)
    return ordered


def describe_filters(
    area_scope: str,
    brazil_regions: list[str] | None = None,
    international_regions: list[str] | None = None,
) -> str:
    """Human summary of the applied filter (spec §6).

    e.g. "Buscando destinos baratos no Brasil: Nordeste, Sudeste." or
    "Buscando destinos baratos no Brasil e exterior: Norte + Europa Ocidental."
    """
    br = brazil_regions or (list(BRAZIL_REGIONS.keys()) if area_scope in (AREA_BRAZIL, AREA_BOTH) else [])
    intl = international_regions or (
        list(INTERNATIONAL_REGIONS.keys()) if area_scope in (AREA_INTERNATIONAL, AREA_BOTH) else []
    )

    if area_scope == AREA_BRAZIL:
        return f"Buscando destinos baratos no Brasil: {', '.join(br)}."
    if area_scope == AREA_INTERNATIONAL:
        return f"Buscando destinos baratos no exterior: {', '.join(intl)}."
    return (
        "Buscando destinos baratos no Brasil e exterior: "
        f"{', '.join(br)} + {', '.join(intl)}."
    )


def validate_geography_catalog() -> list[str]:
    """Return IATA codes in the geography catalog that are unknown to the main
    destinations catalog. Non-blocking: the search still runs (the fallback in
    ``get_destination_info`` handles unknown codes), this is just an internal
    warning for catalog hygiene (spec §3)."""
    try:
        from data.destinations_catalog import BRAZIL_IATAS, DESTINATIONS
    except Exception:
        return []
    known = set(DESTINATIONS.keys()) | set(BRAZIL_IATAS)
    unknown: list[str] = []
    for codes in list(BRAZIL_REGIONS.values()) + list(INTERNATIONAL_REGIONS.values()):
        for code in codes:
            if code.upper() not in known and code.upper() not in unknown:
                unknown.append(code.upper())
    return unknown


# Re-export for convenience.
__all__ = [
    "get_destination_iatas_for_filters",
    "describe_filters",
    "scope_for_area",
    "region_for_iata",
    "validate_geography_catalog",
]
