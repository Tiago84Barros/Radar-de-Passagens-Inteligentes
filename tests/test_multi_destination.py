"""Regression tests guaranteeing the PRESERVED multi-destination search engine
keeps working after the decision-radar refactor.

Covers both preserved layers:
  • per-route engine ........ providers.provider_manager.search_all_providers
  • multi-destination ranker  services.opportunity_service.get_home_deals
and the thin adapter that converts their output to the new opportunity shape.
"""
from datetime import date, timedelta

import pandas as pd

from providers.provider_manager import search_all_providers
from services.multi_destination_adapter import (
    deal_to_opportunity,
    find_cheapest_destinations,
    live_multi_destination_search,
)
from services.opportunity_service import get_home_deals

_OPPORTUNITY_KEYS = {
    "origin_iata",
    "destination_iata",
    "destination_city",
    "destination_country",
    "destination_type",
    "departure_date",
    "return_date",
    "cash_price",
    "estimated_miles",
    "source",
    "score",
    "recommendation",
    "booking_link",
}


def _sample_quotes_df() -> pd.DataFrame:
    dep = date.today() + timedelta(days=45)
    rows = [
        # National
        {"origem": "GRU", "destino": "GIG", "preço": 320.0, "companhia": "GOL",
         "ida": dep, "volta": None, "score": 72, "escalas": 0, "duração_min": 70,
         "provedor": "travelpayouts", "link": "", "via_hub": ""},
        {"origem": "GRU", "destino": "SSA", "preço": 540.0, "companhia": "LATAM",
         "ida": dep, "volta": None, "score": 60, "escalas": 1, "duração_min": 180,
         "provedor": "travelpayouts", "link": "", "via_hub": ""},
        # International
        {"origem": "GRU", "destino": "LIS", "preço": 2890.0, "companhia": "TAP",
         "ida": dep, "volta": None, "score": 80, "escalas": 0, "duração_min": 600,
         "provedor": "travelpayouts", "link": "", "via_hub": ""},
    ]
    return pd.DataFrame(rows)


def test_per_route_engine_still_returns_offers():
    """search_all_providers must still return cheapest-first offers for a route
    (demo mode when no API token is configured)."""
    offers = search_all_providers(
        {
            "origin": "GRU",
            "destination": "GIG",
            "departure_date": date.today() + timedelta(days=30),
            "return_date": None,
            "currency": "BRL",
        }
    )
    assert offers, "per-route search engine returned nothing"
    prices = [float(o.get("price") or 0) for o in offers]
    assert prices == sorted(prices), "offers must be sorted cheapest-first"
    assert all(o.get("origin") and o.get("destination") for o in offers)


def test_multi_destination_ranker_splits_national_and_international():
    national, international = get_home_deals(
        _sample_quotes_df(), national_limit=5, international_limit=5, fill_demo=False
    )
    nat_dests = {d["destination_iata"] for d in national}
    intl_dests = {d["destination_iata"] for d in international}
    assert {"GIG", "SSA"} <= nat_dests
    assert "LIS" in intl_dests


def test_adapter_converts_to_opportunity_shape():
    result = find_cheapest_destinations(
        _sample_quotes_df(), origin="GRU", scope="ambos", limit=5, fill_demo=False
    )
    assert result["national"], "expected national opportunities"
    assert result["international"], "expected international opportunities"
    for opp in result["national"] + result["international"]:
        assert _OPPORTUNITY_KEYS <= set(opp.keys())
        assert opp["recommendation"]
    # Cheapest national first
    nat_prices = [o["cash_price"] for o in result["national"]]
    assert nat_prices == sorted(nat_prices)
    assert result["national"][0]["destination_iata"] == "GIG"


def test_deal_to_opportunity_marks_destination_type():
    nat = deal_to_opportunity({"destination_iata": "GIG", "price_brl": 300, "category": "national"})
    intl = deal_to_opportunity({"destination_iata": "LIS", "price_brl": 3000, "category": "international"})
    assert nat["destination_type"] == "national"
    assert intl["destination_type"] == "international"


def test_live_sweep_uses_preserved_engine_across_destinations():
    """The live sweep reuses search_all_providers per destination and returns
    opportunities sorted by price (demo mode keeps it deterministic-ish)."""
    opps = live_multi_destination_search(
        "GRU", ["GIG", "SSA"], {"departure_date": date.today() + timedelta(days=30)},
        max_destinations=2,
    )
    assert opps, "live multi-destination sweep returned nothing"
    assert all(_OPPORTUNITY_KEYS <= set(o.keys()) for o in opps)
    prices = [o["cash_price"] for o in opps]
    assert prices == sorted(prices)
