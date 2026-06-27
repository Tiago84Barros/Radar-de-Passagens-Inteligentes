import providers.provider_manager as provider_manager


class _DisabledProvider:
    def is_configured(self):
        return False


def test_hybrid_manager_returns_no_fares_when_no_source_is_configured(monkeypatch):
    monkeypatch.setattr(
        provider_manager,
        "SerpApiGoogleFlightsProvider",
        _DisabledProvider,
    )
    monkeypatch.setattr(
        provider_manager,
        "TravelPayoutsProvider",
        _DisabledProvider,
    )
    results = provider_manager.search_all_providers(
        {
            "origin": "BEL",
            "destination": "LIS",
            "departure_date": "2026-09-10",
            "return_date": None,
            "currency": "BRL",
            "adults": 1,
        }
    )
    diagnostic = provider_manager.get_last_provider_diagnostic()

    assert results == []
    assert diagnostic["status"] == "no_confirmed_source"


def test_year_price_calendar_returns_empty_without_published_source(monkeypatch):
    monkeypatch.setattr(
        provider_manager,
        "TravelPayoutsProvider",
        _DisabledProvider,
    )
    results = provider_manager.search_year_price_calendar(
        {
            "origin": "BEL",
            "destination": "LIS",
            "departure_date": "2026-09-10",
            "currency": "BRL",
        }
    )

    assert results == []
