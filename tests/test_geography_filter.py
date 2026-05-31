"""Tests for the geographic filter layer (in front of the preserved engine)."""
from data.geography_catalog import (
    BRAZIL_REGIONS,
    INTERNATIONAL_REGIONS,
    region_for_iata,
)
from services.geography_filter_service import (
    get_destination_iatas_for_filters,
    scope_for_area,
    validate_geography_catalog,
)


def test_brazil_specific_region_only():
    iatas = get_destination_iatas_for_filters("Brasil", brazil_regions=["Nordeste"])
    assert "SSA" in iatas and "REC" in iatas
    assert "GRU" not in iatas  # Sudeste excluded
    assert all(code not in iatas for code in INTERNATIONAL_REGIONS["Europa Ocidental"])


def test_international_specific_region_only():
    iatas = get_destination_iatas_for_filters(
        "Exterior", international_regions=["Europa Ocidental"]
    )
    assert "LIS" in iatas and "CDG" in iatas
    assert "MIA" not in iatas  # América do Norte excluded
    assert "SSA" not in iatas  # no Brazil


def test_no_region_uses_all_of_category():
    # Brasil with no regions selected → all Brazilian airports.
    iatas = get_destination_iatas_for_filters("Brasil", brazil_regions=[])
    expected = {c for codes in BRAZIL_REGIONS.values() for c in codes}
    assert set(iatas) == expected


def test_both_combines_and_dedupes_and_excludes_origin():
    iatas = get_destination_iatas_for_filters(
        "Ambos",
        brazil_regions=["Sudeste"],
        international_regions=["Europa Ocidental"],
        origin="GRU",
    )
    assert "GRU" not in iatas          # origin excluded
    assert "GIG" in iatas              # other Sudeste kept
    assert "LIS" in iatas              # international kept
    assert len(iatas) == len(set(iatas))  # no duplicates


def test_both_empty_uses_everything():
    iatas = get_destination_iatas_for_filters("Ambos", [], [])
    assert "GRU" in iatas and "LIS" in iatas


def test_region_for_iata_lookup():
    assert region_for_iata("LIS") == ("Exterior", "Europa Ocidental")
    assert region_for_iata("SSA") == ("Brasil", "Nordeste")
    assert region_for_iata("ZZZ") == (None, None)


def test_scope_mapping():
    assert scope_for_area("Brasil") == "nacional"
    assert scope_for_area("Exterior") == "internacional"
    assert scope_for_area("Ambos") == "ambos"


def test_catalog_validation_returns_list():
    # Non-blocking hygiene check — must return a list (possibly empty).
    assert isinstance(validate_geography_catalog(), list)
