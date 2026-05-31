"""Tests for the purchase-decision engine."""
from datetime import date, timedelta

from services.decision_engine import (
    REC_BUY,
    REC_MILES,
    REC_MONITOR,
    REC_WAIT,
    build_purchase_recommendation,
)


def _quote(price, **kw):
    base = {
        "price_brl": price,
        "airline": kw.get("airline", "LATAM"),
        "provider": kw.get("provider", "travelpayouts"),
        "score": kw.get("score", 50),
        "departure_date": kw.get("departure_date", date.today() + timedelta(days=60)),
        "stops": kw.get("stops", 0),
        "duration_minutes": kw.get("duration_minutes", 120),
    }
    base.update(kw)
    return base


def test_no_quotes_returns_wait():
    rec = build_purchase_recommendation([], {"max_price": 1000})
    assert rec["recommendation"] == REC_WAIT
    assert rec["best_cash_option"] is None
    assert rec["should_alert"] is False


def test_below_budget_and_below_recent_min_recommends_buy():
    quotes = [_quote(800), _quote(950, airline="GOL")]
    rec = build_purchase_recommendation(
        quotes,
        {"max_price": 1000, "consider_miles": False},
        recent_history={"recent_min": 820, "recent_avg": 1100, "sample_size": 12},
    )
    assert rec["recommendation"] == REC_BUY
    assert rec["best_cash_option"]["price_brl"] == 800
    assert rec["should_alert"] is True


def test_above_budget_recommends_monitor():
    quotes = [_quote(1500, score=40)]
    rec = build_purchase_recommendation(
        quotes,
        {"max_price": 1000, "consider_miles": False},
        recent_history={"recent_avg": 1450},
    )
    assert rec["recommendation"] in {REC_MONITOR, REC_WAIT}


def test_real_award_makes_miles_worth_it():
    # Cheap emission: 20.000 miles + R$ 100 taxes for a R$ 1.200 fare → 0,055/milha
    quotes = [
        _quote(1200, score=75, miles_required=20000, taxes=100),
    ]
    rec = build_purchase_recommendation(
        quotes,
        {"max_price": 1300, "consider_miles": True, "user_min_mile_value": 0.035},
    )
    assert rec["recommendation"] == REC_MILES
    assert rec["best_miles_option"]["mile_value"] >= 0.035
    assert rec["should_alert"] is True


def test_confidence_within_bounds():
    rec = build_purchase_recommendation([_quote(500)], {"max_price": 1000})
    assert 5 <= rec["confidence"] <= 99
