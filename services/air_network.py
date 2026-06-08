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

# ─── International gateway hubs ───────────────────────────────────────────────
# Grandes hubs de conexao FORA do Brasil. Quando a viagem sai do Brasil rumo a
# um destino internacional sem voo direto (ou caro), conectar por aeroportos
# domesticos brasileiros (CGH, BSB...) nao faz sentido — eles nao tem voos
# internacionais para la. O que de fato baixa o preco/abre opcao e conectar
# por grandes hubs internacionais com boa malha de continuacao, ex.:
# GRU -> LIS -> <Europa>, GRU -> MIA -> <EUA>, GRU -> PTY -> <Americas>.
INTERNATIONAL_HUBS: list[str] = [
    "LIS", "MAD", "CDG", "FRA", "AMS",   # portas de entrada na Europa
    "MIA", "JFK", "ATL", "PTY", "BOG",   # America do Norte / Central
    "LIM", "SCL", "EZE",                 # hubs regionais na America do Sul
    "DXB", "IST", "DOH",                 # pontes de longo curso para Asia/Africa/Oceania
]

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

    Two distinct strategies, chosen by route shape:

    - Outbound international (Brazilian origin, non-Brazilian destination):
      candidates come from `INTERNATIONAL_HUBS` — large long-haul connecting
      airports abroad (LIS, MAD, MIA, PTY...). Routing through another
      Brazilian airport here is pointless (e.g. CGH has no flights to Europe);
      the international gateways are where combined fares actually appear.

    - Domestic / inbound-international (destination is Brazilian, or neither
      side is): builds a wider, more diverse pool than a single curated pair
      lookup — editorial picks for the region pair come first (most
      promising), then the nationally-connected primary hubs, then secondary
      hubs based in the origin/destination regions, then generic fallbacks.
      This way, raising `max_hubs` actually surfaces *different* airports
      across Brazil instead of repeating the same two — maximizing the chance
      of finding a cheaper combined route, even when it means changing planes
      along the way.

    Excludes origin and destination from the result. Capped at max_hubs entries.
    """
    origin = origin.upper()
    destination = destination.upper()

    origin_region = get_region(origin)
    dest_region = get_region(destination)

    # Saida internacional do Brasil (origem domestica, destino fora do Brasil):
    # conectar via outro aeroporto brasileiro nao ajuda (ex.: CGH nao tem voo
    # para o exterior). O que de fato amplia o alcance e tentar grandes hubs
    # internacionais — e e exatamente onde voos internacionais "nao aparecem"
    # quando so olhamos a malha domestica brasileira.
    if origin_region is not None and dest_region is None:
        candidates = [h for h in INTERNATIONAL_HUBS if h not in (origin, destination)]
        return candidates[:max_hubs]

    ranked: list[str] = []

    def _add(*codes: str | None) -> None:
        for code in codes:
            if code and code not in ranked:
                ranked.append(code)

    # 1) Editorial picks for this region pair — most promising connections first
    _add(*(_HUB_PREFS.get((origin_region, dest_region)) or ()))
    _add(*(_HUB_PREFS.get((dest_region, origin_region)) or ()))

    # 2) Nationally-connected hubs — almost always worth trying
    _add(*PRIMARY_HUBS)

    # 3) Secondary hubs based in the origin/destination regions — useful for
    # "breaking" the trip near one end of the journey
    for region in (origin_region, dest_region):
        if region:
            _add(*(h for h in SECONDARY_HUBS if h in REGIONS.get(region, frozenset())))

    # 4) Generic fallback for anything still missing
    _add(*_DEFAULT_HUBS)
    _add(*SECONDARY_HUBS)

    candidates = [h for h in ranked if h not in (origin, destination)]
    return candidates[:max_hubs]


def is_domestic(origin: str, destination: str) -> bool:
    """Return True if both airports are in known Brazilian regions."""
    return get_region(origin.upper()) is not None and get_region(destination.upper()) is not None


def hub_route_label(origin: str, hub: str, destination: str) -> str:
    """Human-readable label for a connecting route."""
    return f"{origin} → {hub} → {destination}"
