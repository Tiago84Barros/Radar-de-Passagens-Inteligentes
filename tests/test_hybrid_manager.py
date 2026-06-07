from providers.provider_manager import get_last_provider_diagnostic, search_all_providers, search_year_price_calendar


def test_hybrid_manager_uses_demo_when_no_token(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)

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

    assert results
    assert results[0]["source"] == "travelpayouts_demo"
    assert diagnostic["status"] == "demo_no_token"
    get_settings.cache_clear()


def test_year_price_calendar_returns_demo_prices_without_token(monkeypatch):
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

    assert len(results) >= 52
    assert {item["airline"] for item in results}
    assert all(item["source"] == "travelpayouts_demo_calendar" for item in results)
    get_settings.cache_clear()
