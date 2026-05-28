from app.location_resolver import search_locations, resolve_location


def test_iata_code_is_accepted_directly():
    location = resolve_location("bel")
    assert location is not None
    assert location.code == "BEL"
    assert location.source == "codigo informado"


def test_search_locations_lists_direct_iata_code():
    options = search_locations("mco")
    assert options
    assert options[0].code == "MCO"
    assert "codigo IATA" in options[0].label


def test_country_name_can_fallback_to_main_city_code():
    location = resolve_location("Portugal")
    assert location is not None
    assert location.code == "LIS"
    assert location.location_type in {"city", "country"}
