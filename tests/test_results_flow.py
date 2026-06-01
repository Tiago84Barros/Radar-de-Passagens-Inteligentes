"""Tests for fare variants, airline info/logo and destination images."""
from data.airlines_catalog import get_airline_info, logo_url_for
from data.destinations_catalog import get_destination_image
from services.opportunity_service import select_fare_variants


# ── Fare variants ─────────────────────────────────────────────────────────────
def _d(airline, price, dur=None):
    return {"airline": airline, "price_brl": price, "duration_minutes": dur}


def test_variants_keep_cheapest_and_dedupe():
    deals = [_d("G3", 480, 70), _d("G3", 485, 75), _d("AD", 520, 180), _d("LA", 610, 800)]
    v = select_fare_variants(deals, max_variants=3)
    assert v[0]["price_brl"] == 480                      # cheapest kept, first
    airlines = [x["airline"] for x in v]
    assert airlines.count("G3") == 1                     # near-duplicate removed
    assert len(v) == 3 and {"G3", "AD", "LA"} == set(airlines)  # diversified


def test_variants_prefer_under_12h_but_fallback():
    deals = [_d("G3", 500, 1500), _d("AD", 700, 120), _d("LA", 900, 200)]
    v = select_fare_variants(deals, max_variants=2, preferred_max_duration_hours=12)
    assert v[0]["price_brl"] == 500                      # cheapest always included
    # The second pick should prefer a sub-12h option (AD 120min) over price order.
    assert any(x["airline"] == "AD" for x in v)


def test_variants_tolerate_missing_duration():
    deals = [_d("G3", 500, None), _d("AD", 600, None)]
    v = select_fare_variants(deals, max_variants=3)
    assert len(v) == 2


def test_variants_empty():
    assert select_fare_variants([], 3) == []


# ── Airline info / logo ───────────────────────────────────────────────────────
def test_airline_info_has_logo_and_full_name():
    info = get_airline_info("G3")
    assert info["code"] == "G3"
    assert info["name"] == "GOL Linhas Aéreas"
    assert info["logo_url"].endswith("/G3.png")


def test_airline_info_unknown_safe():
    info = get_airline_info("ZZ")
    assert info["logo_url"] == ""           # no logo → UI uses plane fallback
    assert info["name"]                      # still returns a name string


def test_logo_url_for_unknown_is_empty():
    assert logo_url_for("ZZ") == ""


# ── Destination images ────────────────────────────────────────────────────────
def test_image_by_iata():
    r = get_destination_image(iata="BEL")
    assert r["is_fallback"] is False and r["url"].startswith("http")


def test_image_by_city_normalised():
    # Accents/case must not matter.
    r = get_destination_image(city="belém")
    assert r["is_fallback"] is False
    assert get_destination_image(city="Nova York")["is_fallback"] is False


def test_image_fallback_is_marked():
    r = get_destination_image(iata="ZZZ", country="Brasil")
    assert r["is_fallback"] is True
    assert " " not in r["url"]              # seed sanitised, valid URL
