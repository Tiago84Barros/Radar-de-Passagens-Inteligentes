"""Adapter around the PRESERVED multi-destination search engine.

────────────────────────────────────────────────────────────────────────────
PRESERVED ENGINE — DO NOT REMOVE OR REWRITE
────────────────────────────────────────────────────────────────────────────
The app already ships a working capability to look at many destinations and
return the cheapest ones. It lives in two layers, both reused here unchanged:

  1. Per-route search engine
       providers.provider_manager.search_all_providers(search_params)
     Queries Travelpayouts + scrapers + multi-segment hubs for ONE origin→dest
     route. Used by services.monitoring_service.run_search_once when collecting.

  2. Multi-destination ranking engine
       services.opportunity_service.get_home_deals(df_quotes, ...)
     Ranks the cheapest deal per (origin, destination) across every collected
     destination and splits them into national vs international.

This module is a THIN WRAPPER. It does not replace either engine — it only
adapts their output to the new "opportunity" shape used by the decision-radar
UI and attaches a per-destination recommendation. If the engines change, this
adapter adapts; the engines stay the single source of truth.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from data.destinations_catalog import BRAZIL_IATAS, get_destination_info
from services.decision_engine import build_purchase_recommendation
from services.miles_service import DEFAULT_CENTS_PER_MILE
# Preserved engines (imported, never reimplemented):
from services.opportunity_service import get_home_deals


def deal_to_opportunity(
    deal: dict,
    *,
    origin_iata: str | None = None,
    search_params: dict | None = None,
    min_mile_value: float = DEFAULT_CENTS_PER_MILE,
) -> dict:
    """Convert one enriched deal (engine output) into the spec opportunity shape.

    The recommendation is computed per-destination by the decision engine so each
    card can say "comprar / monitorar / usar milhas" on its own.
    """
    price = float(deal.get("price_brl") or deal.get("preço") or 0)
    dest_iata = str(deal.get("destination_iata") or deal.get("destino") or "").upper()
    info = get_destination_info(dest_iata) if dest_iata else {}
    category = deal.get("category") or _category(dest_iata)

    params = dict(search_params or {})
    params.setdefault("max_price", None)
    rec = build_purchase_recommendation([deal], params)

    # Geographic region/continent (for badges and alerts). Falls back to the
    # broad national/international label when the IATA isn't in the geo catalog.
    from services.geography_filter_service import region_for_iata

    region_scope, region_label = region_for_iata(dest_iata)

    return {
        "origin_iata": str(origin_iata or deal.get("origin_iata") or deal.get("origem") or "").upper(),
        "destination_iata": dest_iata,
        "destination_city": deal.get("destination_city") or info.get("city") or dest_iata,
        "destination_country": deal.get("destination_country") or info.get("country") or "",
        "destination_type": "national" if category == "national" else "international",
        "region": region_label or ("Brasil" if category == "national" else "Exterior"),
        "region_scope": region_scope or ("Brasil" if category == "national" else "Exterior"),
        "departure_date": deal.get("departure_date"),
        "return_date": deal.get("return_date"),
        "cash_price": price,
        "estimated_miles": int(deal.get("estimated_miles") or 0),
        "mile_value": (rec.get("best_cash_option") or {}).get("mile_value", min_mile_value),
        "source": deal.get("provider") or deal.get("source") or "—",
        "score": int(deal.get("score") or 0),
        "recommendation": rec["recommendation"],
        "recommendation_confidence": rec["confidence"],
        "recommendation_reason": rec["main_reason"],
        "booking_link": deal.get("booking_link") or deal.get("link") or "",
        # Visual fields for the postcard cards (kept from the catalog/engine).
        "image_url": deal.get("image_url") or info.get("image_url") or "",
        "gradient": deal.get("gradient") or info.get("gradient") or "",
        "postcard_label": deal.get("postcard_label") or info.get("postcard_label") or "",
        "is_demo": bool(deal.get("is_demo")),
    }


def find_cheapest_destinations(
    df_quotes: pd.DataFrame,
    *,
    origin: str | None = None,
    scope: str = "ambos",
    limit: int = 6,
    fill_demo: bool = True,
    search_params: dict | None = None,
    min_mile_value: float = DEFAULT_CENTS_PER_MILE,
    candidate_iatas: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Rank the cheapest destinations as opportunities, split Brazil vs Exterior.

    Wraps the preserved ``get_home_deals`` ranking engine and converts its output
    to the opportunity shape. ``scope`` ∈ {"nacional", "internacional", "ambos"}
    controls which buckets are returned. ``origin`` filters real deals to that
    origin when provided (demo deals are origin-agnostic).

    ``candidate_iatas`` (optional) restricts results to those destination airports
    — the geographic filter applied before ranking. ``None``/empty keeps every
    destination in the chosen scope (preserves the previous behaviour).

    Returns ``{"national": [...], "international": [...]}``.
    """
    cents = float(min_mile_value or DEFAULT_CENTS_PER_MILE)
    allow = {c.upper() for c in (candidate_iatas or [])}

    # Pull a generous slice from the preserved engine, then filter/convert.
    national_deals, international_deals = get_home_deals(
        df_quotes,
        cents_per_mile=cents,
        national_limit=max(limit * 2, 8),
        international_limit=max(limit * 2, 8),
        fill_demo=fill_demo,
    )

    origin_code = (origin or "").upper().strip()

    def _prep(deals: list[dict]) -> list[dict]:
        items = deals
        if origin_code:
            filtered = [
                d for d in deals
                if not d.get("origin_iata") or str(d.get("origin_iata")).upper() == origin_code
            ]
            # Only narrow to the origin if it leaves us something to show.
            if filtered:
                items = filtered
        # Geographic filter: keep only eligible destination airports.
        if allow:
            items = [
                d for d in items
                if str(d.get("destination_iata") or d.get("destino") or "").upper() in allow
            ]
        opps = [
            deal_to_opportunity(
                d, origin_iata=origin_code or None, search_params=search_params, min_mile_value=cents
            )
            for d in items
        ]
        opps.sort(key=lambda o: o["cash_price"] if o["cash_price"] > 0 else float("inf"))
        return opps[:limit]

    result: dict[str, list[dict]] = {"national": [], "international": []}
    if scope in {"nacional", "ambos"}:
        result["national"] = _prep(national_deals)
    if scope in {"internacional", "ambos"}:
        result["international"] = _prep(international_deals)
    return result


def live_multi_destination_search(
    origin: str,
    candidate_destinations: list[str],
    search_params: dict | None = None,
    *,
    max_destinations: int = 8,
    min_mile_value: float = DEFAULT_CENTS_PER_MILE,
) -> list[dict]:
    """Live sweep: run the PRESERVED per-route engine across many destinations.

    Reuses ``providers.provider_manager.search_all_providers`` once per candidate
    destination (capped by ``max_destinations`` to stay responsive) and keeps the
    cheapest offer per destination. This is the explicit reuse of the existing
    engine for a multi-destination query — it never reimplements provider logic.

    Falls back gracefully: any destination that errors is skipped, so a single
    failing route never breaks the sweep. Returns opportunities sorted by price.
    """
    # Imported lazily so importing this adapter never triggers provider/network code.
    from providers.provider_manager import search_all_providers

    origin = (origin or "").upper().strip()
    params_base = dict(search_params or {})
    opportunities: list[dict] = []

    for dest in [d.upper() for d in candidate_destinations if d][:max_destinations]:
        if dest == origin:
            continue
        params = dict(params_base, origin=origin, destination=dest)
        try:
            offers = search_all_providers(params)
        except Exception:
            # A single failing route must never break the multi-destination sweep.
            continue
        if not offers:
            continue
        cheapest = min(offers, key=lambda o: float(o.get("price") or 0) or float("inf"))
        deal = _offer_to_deal(cheapest, origin, dest)
        opportunities.append(
            deal_to_opportunity(
                deal, origin_iata=origin, search_params=params_base, min_mile_value=min_mile_value
            )
        )

    opportunities.sort(key=lambda o: o["cash_price"] if o["cash_price"] > 0 else float("inf"))
    return opportunities


# ── helpers ──────────────────────────────────────────────────────────────────

def _category(iata: str) -> str:
    return "national" if (iata or "").upper() in BRAZIL_IATAS else "international"


def _offer_to_deal(offer: dict[str, Any], origin: str, destination: str) -> dict:
    """Convert a raw provider offer into the enriched-deal shape used internally."""
    from services.miles_service import enrich_deal_with_miles

    info = get_destination_info(destination)
    deal = {
        "origin_iata": origin,
        "destination_iata": destination,
        "destination_city": info.get("city", destination),
        "destination_country": info.get("country", ""),
        "category": _category(destination),
        "departure_date": offer.get("departure_date"),
        "return_date": offer.get("return_date"),
        "price_brl": float(offer.get("price") or 0),
        "airline": offer.get("airline") or "",
        "provider": offer.get("provider") or offer.get("source") or "",
        "booking_link": offer.get("booking_link") or "",
        "stops": offer.get("stops"),
        "duration_minutes": offer.get("duration_minutes"),
        "score": int(offer.get("score") or 0),
        "image_url": info.get("image_url", ""),
        "gradient": info.get("gradient", ""),
        "postcard_label": info.get("postcard_label", ""),
        "is_demo": bool((offer.get("raw_payload") or {}).get("demo")),
    }
    return enrich_deal_with_miles(deal)
