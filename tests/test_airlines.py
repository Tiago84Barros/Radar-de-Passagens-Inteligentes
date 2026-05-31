"""Tests for full airline-name resolution."""
from data.airlines_catalog import get_airline_name


def test_known_iata_codes_resolve_to_full_name():
    assert get_airline_name("G3") == "GOL Linhas Aéreas"
    assert get_airline_name("AD") == "Azul Linhas Aéreas"
    assert get_airline_name("LA") == "LATAM Airlines"
    assert get_airline_name("TP") == "TAP Air Portugal"


def test_short_names_resolve_to_full_name():
    assert get_airline_name("GOL") == "GOL Linhas Aéreas"
    assert get_airline_name("LATAM") == "LATAM Airlines"
    assert get_airline_name("Azul") == "Azul Linhas Aéreas"


def test_full_name_is_kept():
    assert get_airline_name("TAP Air Portugal") == "TAP Air Portugal"


def test_combined_legs_are_kept():
    assert get_airline_name("LA + TP") == "LA + TP"


def test_empty_and_unknown():
    assert get_airline_name("") == "Companhia não informada"
    assert get_airline_name(None) == "Companhia não informada"
    assert get_airline_name("ZZ") == "Companhia não identificada"


def test_partial_match():
    assert get_airline_name("GOL Linhas Aéreas S.A.") == "GOL Linhas Aéreas"
