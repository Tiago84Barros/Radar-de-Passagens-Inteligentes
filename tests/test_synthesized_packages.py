from datetime import date

from streamlit_app import _filter_return_options, _run_manual_search, _synthesize_packages


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


def test_return_options_before_outbound_are_hidden():
    options = [
        {"departure_date": "2026-07-15", "price_brl": 400.0},
        {"departure_date": "2026-07-31", "price_brl": 600.0},
    ]

    filtered = _filter_return_options(options, date(2026, 7, 24))

    assert filtered == [{"departure_date": "2026-07-31", "price_brl": 600.0}]


def test_manual_search_filters_return_cards_before_outbound(monkeypatch):
    calls = []

    def fake_search(params):
        calls.append(params)
        if params["origin"] == "GRU" and params["destination"] == "BEL" and params.get("return_date") is None:
            return [
                _raw_offer("2026-07-02", 400),
                _raw_offer("2026-07-18", 600),
            ]
        return []

    monkeypatch.setattr("streamlit_app.search_all_providers", fake_search)
    monkeypatch.setattr("streamlit_app.get_last_provider_diagnostic", lambda: {})

    results = _run_manual_search(_form())

    assert [item["departure_date"] for item in results["return"]] == ["2026-07-18"]
    inbound_call = next(call for call in calls if call["origin"] == "GRU" and call["destination"] == "BEL")
    assert inbound_call["min_departure_date"] == date(2026, 7, 10)


def _raw_offer(departure, price):
    return {
        "provider": "travelpayouts",
        "source": "travelpayouts",
        "origin": "GRU",
        "destination": "BEL",
        "departure_date": departure,
        "airline": "LA",
        "price": float(price),
        "currency": "BRL",
        "stops": 0,
        "duration_minutes": 120,
        "booking_link": "https://latamairlines.com",
        "source_confidence": "real",
    }
