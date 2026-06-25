from providers.serpapi_provider import SerpApiGoogleFlightsProvider


def test_normalizes_google_flights_payload_from_serpapi():
    provider = SerpApiGoogleFlightsProvider()
    payload = {
        "search_metadata": {
            "id": "search-123",
            "google_flights_url": "https://www.google.com/travel/flights/search?tfs=abc",
        },
        "best_flights": [
            {
                "price": 717,
                "total_duration": 120,
                "flights": [
                    {
                        "departure_airport": {"id": "BEL", "time": "2026-07-01 06:45"},
                        "arrival_airport": {"id": "FOR", "time": "2026-07-01 08:45"},
                        "airline": "Azul",
                        "flight_number": "AD4181",
                        "duration": 120,
                    }
                ],
            }
        ],
    }

    results = provider.normalize_response(
        payload,
        origin="BEL",
        destination="FOR",
        departure_date="2026-07-01",
        return_date=None,
        currency="BRL",
    )

    assert len(results) == 1
    assert results[0]["provider"] == "serpapi_google_flights"
    assert results[0]["source_name"] == "Google Flights via SerpApi"
    assert results[0]["source_verified"] is True
    assert results[0]["source_url"].startswith("https://www.google.com/travel/flights")
    assert results[0]["origin"] == "BEL"
    assert results[0]["destination"] == "FOR"
    assert results[0]["departure_date"] == "2026-07-01"
    assert results[0]["airline"] == "Azul"
    assert results[0]["flight_number"] == "AD4181"
    assert results[0]["price"] == 717.0
    assert results[0]["duration_minutes"] == 120
    assert results[0]["stops"] == 0


def test_builds_serpapi_query_params_from_search_request(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    from app.settings import get_settings

    get_settings.cache_clear()
    provider = SerpApiGoogleFlightsProvider()
    params = provider._build_params(
        origin="bel",
        destination="for",
        departure_date="2026-07-01",
        return_date="2026-07-06",
        currency="BRL",
        adults=2,
        max_stops=0,
        max_duration_minutes=180,
    )

    assert params["engine"] == "google_flights"
    assert params["api_key"] == "test-key"
    assert params["departure_id"] == "BEL"
    assert params["arrival_id"] == "FOR"
    assert params["outbound_date"] == "2026-07-01"
    assert params["return_date"] == "2026-07-06"
    assert params["type"] == "1"
    assert params["currency"] == "BRL"
    assert params["adults"] == 2
    assert params["stops"] == "1"
    assert params["max_duration"] == 180
    get_settings.cache_clear()
