from datetime import date

from app.db import FlightQuote, FlightSearch
from app.pricing import evaluate_quote


def _search(max_price: float = 2000) -> FlightSearch:
    return FlightSearch(
        owner_email="demo@radar.local",
        origin="GRU",
        destination="LIS",
        departure_date=date.today(),
        max_price=max_price,
        currency="BRL",
    )


def test_alert_when_price_is_below_limit():
    decision = evaluate_quote(_search(2000), 1700, [])
    assert decision.should_alert is True
    assert decision.opportunity in {"boa_oportunidade", "excelente_oportunidade"}


def test_historical_low_can_be_rare_opportunity():
    history = [
        FlightQuote(
            search_id=1,
            origin="GRU",
            destination="LIS",
            departure_date=date.today(),
            airline="TAP",
            price=2600,
            currency="BRL",
            duration_minutes=600,
            stops=0,
            booking_link="https://example.com",
            provider="mock",
        ),
        FlightQuote(
            search_id=1,
            origin="GRU",
            destination="LIS",
            departure_date=date.today(),
            airline="LATAM",
            price=2400,
            currency="BRL",
            duration_minutes=620,
            stops=1,
            booking_link="https://example.com",
            provider="mock",
        ),
    ]
    decision = evaluate_quote(_search(2500), 1900, history)
    assert decision.should_alert is True
    assert decision.is_historical_low is True
    assert decision.opportunity == "oportunidade_rara"
