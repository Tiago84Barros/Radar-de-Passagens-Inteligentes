import services.multi_segment_search as multi


def _leg(origin, destination, price, departure_at, duration, airline="LA"):
    return {
        "provider": "travelpayouts",
        "source": "travelpayouts",
        "origin": origin,
        "destination": destination,
        "departure_date": departure_at[:10],
        "departure_at": departure_at,
        "airline": airline,
        "price": float(price),
        "currency": "BRL",
        "duration_minutes": duration,
        "stops": 0,
        "booking_link": "https://www.aviasales.com/search",
    }


def _params():
    return {
        "origin": "BEL",
        "destination": "FLN",
        "departure_date": "2026-07-10",
        "return_date": None,
        "date_flex_days": 0,
    }


def test_combined_route_requires_six_hour_real_layover(monkeypatch):
    monkeypatch.setattr(multi, "find_candidate_hubs", lambda *args: ["GRU"])
    leg1 = _leg("BEL", "GRU", 400, "2026-07-10T08:00:00-03:00", 120)
    leg2 = _leg("GRU", "FLN", 400, "2026-07-10T16:00:00-03:00", 90)

    def search(params):
        return [leg1] if params["origin"] == "BEL" else [leg2]

    results = multi.search_via_connections(
        _params(),
        search,
        direct_results=[{"price": 1200.0, "duration_minutes": 300}],
    )

    assert len(results) == 1
    assert results[0]["connections"][0]["wait_minutes"] == 360
    assert results[0]["separate_ticket"] is True


def test_combined_route_rejects_short_or_unknown_layover(monkeypatch):
    monkeypatch.setattr(multi, "find_candidate_hubs", lambda *args: ["GRU"])
    leg1 = _leg("BEL", "GRU", 400, "2026-07-10T08:00:00-03:00", 120)
    short_leg2 = _leg("GRU", "FLN", 400, "2026-07-10T15:00:00-03:00", 90)

    def short_search(params):
        return [leg1] if params["origin"] == "BEL" else [short_leg2]

    assert multi.search_via_connections(_params(), short_search, direct_results=[]) == []

    no_time = {**short_leg2, "departure_at": "2026-07-10"}

    def unknown_search(params):
        return [leg1] if params["origin"] == "BEL" else [no_time]

    assert multi.search_via_connections(_params(), unknown_search, direct_results=[]) == []


def test_combined_route_rejects_extreme_duration_penalty(monkeypatch):
    monkeypatch.setattr(multi, "find_candidate_hubs", lambda *args: ["GRU"])
    leg1 = _leg("BEL", "GRU", 300, "2026-07-10T08:00:00-03:00", 120)
    leg2 = _leg("GRU", "FLN", 300, "2026-07-10T16:00:00-03:00", 120)

    def search(params):
        return [leg1] if params["origin"] == "BEL" else [leg2]

    results = multi.search_via_connections(
        _params(),
        search,
        direct_results=[{"price": 1000.0, "duration_minutes": 120}],
    )

    assert results == []
