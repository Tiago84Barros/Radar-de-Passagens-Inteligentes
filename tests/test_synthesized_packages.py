from datetime import date

from streamlit_app import _synthesize_packages


def _leg(price, departure, *, airline="LA", link="https://latamairlines.com"):
    return {
        "price_brl": float(price),
        "airline": airline,
        "departure_date": departure,
        "duration_minutes": 120,
        "stops": 0,
        "booking_link": link,
        "source_confidence": "real",
    }


def _form():
    return {
        "origin_iata": "BEL",
        "destination_iata": "GRU",
        "departure_date": date(2026, 7, 10),
        "return_date": date(2026, 7, 17),
    }


def test_synthesized_package_uses_actual_dates_and_marks_separate_reservations():
    packages = _synthesize_packages(
        [_leg(500, "2026-07-11")],
        [_leg(400, "2026-07-18")],
        _form(),
        0.035,
    )

    assert len(packages) == 1
    package = packages[0]
    assert package["departure_date"] == date(2026, 7, 11)
    assert package["return_date"] == date(2026, 7, 18)
    assert package["separate_ticket"] is True
    assert package["separate_round_trip"] is True
    assert package["outbound_booking_link"]
    assert package["return_booking_link"]


def test_synthesized_package_rejects_return_before_departure():
    packages = _synthesize_packages(
        [_leg(500, "2026-07-20")],
        [_leg(400, "2026-07-02")],
        _form(),
        0.035,
    )

    assert packages == []


def test_synthesized_package_preserves_requested_trip_duration():
    packages = _synthesize_packages(
        [_leg(500, "2026-07-11")],
        [_leg(400, "2026-07-25")],
        _form(),
        0.035,
    )

    assert packages == []
