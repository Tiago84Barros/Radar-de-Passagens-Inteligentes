from __future__ import annotations

"""
Brazilian air network topology for multi-segment route discovery.

The goal is to find cheap combined routes like:
  BEL → GRU → FLN   (instead of only BEL → FLN direct)

We define geographic regions and preferred hub airports to check
as intermediate connections based on the origin/destination pair.
"""

# ─── Airport regions ──────────────────────────────────────────────────────────

REGIONS: dict[str, frozenset[str]] = {
    "norte": frozenset({
        "BEL", "MAO", "STM", "ATM", "OPS", "SLZ", "IMP",
        "BVB", "MCP", "PVH", "RBR",
    }),
    "nordeste": frozenset({
        "FOR", "REC", "SSA", "NAT", "MCZ", "JPA", "AJU",
        "JDO", "IOS", "BPS", "PNZ", "THE", "CPV",
    }),
    "centro_oeste": frozenset({
        "BSB", "GYN", "CGR", "CGB", "PMW",
    }),
    "sudeste": frozenset({
        "GRU", "CGH", "VCP", "GIG", "SDU",
        "CNF", "PLU", "VIX", "UDI",
    }),
    "sul": frozenset({
        "CWB", "POA", "FLN", "LDB", "MGF",
        "XAP", "CCM", "JOI",
    }),
}

# ─── Hubs (ordered by connectivity, most connected first) ─────────────────────

# Airports that serve as primary connection points within Brazil
PRIMARY_HUBS: list[str] = ["GRU", "CGH", "GIG", "BSB"]

# Secondary hubs: major airports in each region
SECONDARY_HUBS: list[str] = ["SSA", "FOR", "REC", "MAO", "BEL", "CWB", "POA", "FLN", "CNF"]

ALL_HUBS: list[str] = PRIMARY_HUBS + SECONDARY_HUBS

# ─── Preferred hubs per route type ────────────────────────────────────────────
# Key: (origin_region, destination_region)
# Value: ordered list of hubs to try (most promising first)
# GRU is Brazil's biggest hub — almost always included.

_HUB_PREFS: dict[tuple[str, str], list[str]] = {
    ("norte",        "sul"):          ["GRU", "BSB", "GIG"],
    ("norte",        "nordeste"):     ["BSB", "GRU"],
    ("norte",        "sudeste"):      ["BSB", "GRU"],
    ("norte",        "centro_oeste"): ["GRU", "BSB"],
    ("nordeste",     "sul"):          ["GRU", "GIG", "BSB"],
    ("nordeste",     "sudeste"):      ["GRU", "GIG"],
    ("nordeste",     "centro_oeste"): ["GRU", "BSB"],
    ("nordeste",     "norte"):        ["GRU", "BSB"],
    ("sul",          "norte"):        ["GRU", "BSB", "GIG"],
    ("sul",          "nordeste"):     ["GRU", "GIG"],
    ("sul",          "centro_oeste"): ["GRU", "BSB"],
    ("sudeste",      "norte"):        ["BSB", "GRU"],
    ("sudeste",      "nordeste"):     ["GRU", "GIG"],
    ("sudeste",      "sul"):          ["GRU", "CGH"],
    ("centro_oeste", "norte"):        ["GRU", "BSB"],
    ("centro_oeste", "nordeste"):     ["GRU", "BSB"],
    ("centro_oeste", "sul"):          ["GRU", "GIG"],
    ("centro_oeste", "sudeste"):      ["GRU", "BSB"],
}

_DEFAULT_HUBS: list[str] = ["GRU", "BSB"]


def get_region(iata: str) -> str | None:
    """Return the geographic region name for a given IATA code."""
    for region, airports in REGIONS.items():
        if iata in airports:
            return region
    return None


def find_candidate_hubs(
    origin: str,
    destination: str,
    max_hubs: int = 2,
) -> list[str]:
    """
    Return a ranked list of hub airports to try as 1-stop connections.

    Excludes origin and destination from the result.
    Capped at max_hubs entries.
    """
    origin = origin.upper()
    destination = destination.upper()

    origin_region = get_region(origin)
    dest_region = get_region(destination)

    # Look up the preferred list (try both directions)
    hubs = (
        _HUB_PREFS.get((origin_region, dest_region))
        or _HUB_PREFS.get((dest_region, origin_region))
        or list(_DEFAULT_HUBS)
    )

    # Never suggest the origin or destination as a hub
    hubs = [h for h in hubs if h not in (origin, destination)]

    # Make sure GRU is always at least attempted (unless it IS origin/dest)
    if "GRU" not in hubs and "GRU" not in (origin, destination):
        hubs = ["GRU"] + hubs

    return hubs[:max_hubs]


def is_domestic(origin: str, destination: str) -> bool:
    """Return True if both airports are in known Brazilian regions."""
    return get_region(origin.upper()) is not None and get_region(destination.upper()) is not None


def hub_route_label(origin: str, hub: str, destination: str) -> str:
    """Human-readable label for a connecting route."""
    return f"{origin} → {hub} → {destination}"
