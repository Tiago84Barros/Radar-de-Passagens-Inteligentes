"""Tests for the cash-vs-miles engine."""
from services.miles_service import (
    calculate_mile_value,
    compare_cash_vs_miles,
    estimate_miles_from_cash_price,
    format_miles,
)


def test_estimate_miles_from_cash_price_matches_default_rate():
    # R$ 700 / 0,035 = 20.000 milhas (rounded to nearest 500)
    assert estimate_miles_from_cash_price(700) == 20000


def test_calculate_mile_value_spec_example():
    # R$ 1.500 cash, 25.000 miles + R$ 150 taxes → (1500-150)/25000 = 0,054
    assert calculate_mile_value(1500, 25000, taxes=150) == 0.054


def test_calculate_mile_value_handles_zero_miles():
    assert calculate_mile_value(1500, 0, taxes=0) == 0.0


def test_compare_recommends_miles_when_value_above_floor():
    result = compare_cash_vs_miles(1500, 25000, taxes=150, user_min_mile_value=0.035)
    assert result["worth_miles"] is True
    assert result["recommendation"] == "Melhor usar milhas"
    assert result["mile_value"] == 0.054


def test_compare_recommends_cash_when_value_below_floor():
    # Expensive emission: 60.000 miles for a R$ 1.000 ticket → 0,0166/milha
    result = compare_cash_vs_miles(1000, 60000, taxes=0, user_min_mile_value=0.035)
    assert result["worth_miles"] is False
    assert result["recommendation"] == "Melhor pagar em dinheiro"


def test_format_miles_brazilian_style():
    assert format_miles(18000) == "18.000 milhas"
