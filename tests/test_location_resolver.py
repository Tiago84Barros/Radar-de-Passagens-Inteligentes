from app.location_resolver import resolve_location


def test_iata_code_is_accepted_directly():
    location = resolve_location("bel")
    assert location is not None
    assert location.code == "BEL"
    assert location.source == "codigo informado"


def test_country_name_can_fallback_to_main_city_code():
    location = resolve_location("Portugal")
    assert location is not None
    assert location.code == "LIS"
    assert location.location_type in {"city", "country"}
