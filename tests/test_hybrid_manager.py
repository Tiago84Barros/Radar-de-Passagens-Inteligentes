from providers.provider_manager import get_last_provider_diagnostic, search_all_providers, search_year_price_calendar


def test_hybrid_manager_returns_no_fares_when_no_source_is_configured(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from app.settings import get_settings

    get_settings.cache_clear()
    results = search_all_providers(
        {
            "origin": "BEL",
            "destination": "LIS",
            "departure_date": "2026-09-10",
            "return_date": None,
            "currency": "BRL",
            "adults": 1,
        }
    )
    diagnostic = get_last_provider_diagnostic()

    assert results == []
    assert diagnostic["status"] == "no_confirmed_source"
    get_settings.cache_clear()


def test_year_price_calendar_returns_empty_without_published_source(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)

    from app.settings import get_settings

    get_settings.cache_clear()
    results = search_year_price_calendar(
        {
            "origin": "BEL",
            "destination": "LIS",
            "departure_date": "2026-09-10",
            "currency": "BRL",
        }
    )

    assert results == []
    get_settings.cache_clear()
