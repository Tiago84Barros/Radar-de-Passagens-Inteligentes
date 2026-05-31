"""Geographic grouping layer for the multi-destination search.

This is ONLY a grouping catalog: it maps Brazilian regions and international
regions/continents to the airport (IATA) codes that belong to them. It does not
duplicate the rich destination metadata in ``data.destinations_catalog`` (city,
country, image, etc.) — that stays the single source of truth and is looked up
by IATA when needed.

Used by ``services.geography_filter_service`` to turn a user's region selection
into the list of candidate destinations handed to the preserved search engine.
The lists are an MVP starting point and can be expanded freely.
"""
from __future__ import annotations

# ── Brazil: the five official macro-regions ──────────────────────────────────
BRAZIL_REGIONS: dict[str, list[str]] = {
    "Norte": ["BEL", "MAO", "STM", "PVH", "RBR", "MCP", "BVB", "PMW"],
    "Nordeste": ["SSA", "REC", "FOR", "NAT", "MCZ", "AJU", "SLZ", "THE", "JPA"],
    "Centro-Oeste": ["BSB", "CGB", "CGR", "GYN"],
    "Sudeste": ["GRU", "CGH", "VCP", "GIG", "SDU", "CNF", "VIX"],
    "Sul": ["POA", "CWB", "FLN", "NVT", "JOI", "IGU", "LDB"],
}

# ── International regions / continents ────────────────────────────────────────
INTERNATIONAL_REGIONS: dict[str, list[str]] = {
    "América do Sul, exceto Brasil": ["EZE", "AEP", "SCL", "MVD", "LIM", "BOG", "UIO", "ASU", "LPB"],
    "América do Norte": ["MIA", "MCO", "JFK", "EWR", "LAX", "SFO", "ORD", "YYZ", "YUL", "MEX", "CUN"],
    "América Central": ["PTY", "SJO", "GUA", "SAL", "MGA"],
    "Caribe": ["PUJ", "SDQ", "AUA", "CUR", "HAV", "MBJ", "NAS"],
    "Europa Ocidental": ["LIS", "OPO", "MAD", "BCN", "PAR", "CDG", "ORY", "AMS", "BRU"],
    "Europa Oriental": ["WAW", "PRG", "BUD", "OTP", "SOF", "BEG"],
    "Europa do Norte": ["LHR", "LGW", "DUB", "CPH", "ARN", "OSL", "HEL"],
    "Europa do Sul": ["FCO", "MXP", "VCE", "ATH", "IST", "MLA"],
    "África": ["JNB", "CPT", "CAI", "CMN", "RAK", "ADD"],
    "Oriente Médio": ["DXB", "DOH", "AUH", "TLV", "AMM"],
    "Ásia": ["NRT", "HND", "ICN", "BKK", "SIN", "HKG", "PEK", "PVG", "DEL"],
    "Oceania": ["SYD", "MEL", "AKL", "BNE"],
}

# Area-scope labels used in the sidebar ("Área da busca").
AREA_BRAZIL = "Brasil"
AREA_INTERNATIONAL = "Exterior"
AREA_BOTH = "Ambos"


# ── Reverse lookups (IATA → region / scope) for badges and alerts ────────────
def _build_reverse() -> dict[str, tuple[str, str]]:
    """IATA → (scope_label, region_label). First match wins for shared codes."""
    rev: dict[str, tuple[str, str]] = {}
    for region, codes in BRAZIL_REGIONS.items():
        for code in codes:
            rev.setdefault(code.upper(), (AREA_BRAZIL, region))
    for region, codes in INTERNATIONAL_REGIONS.items():
        for code in codes:
            rev.setdefault(code.upper(), (AREA_INTERNATIONAL, region))
    return rev


_IATA_TO_REGION: dict[str, tuple[str, str]] = _build_reverse()


def region_for_iata(iata: str) -> tuple[str | None, str | None]:
    """Return ``(scope_label, region_label)`` for an IATA, or (None, None)."""
    return _IATA_TO_REGION.get((iata or "").upper(), (None, None))


def all_brazil_iatas() -> list[str]:
    out: list[str] = []
    for codes in BRAZIL_REGIONS.values():
        out.extend(codes)
    return out


def all_international_iatas() -> list[str]:
    out: list[str] = []
    for codes in INTERNATIONAL_REGIONS.values():
        out.extend(codes)
    return out
