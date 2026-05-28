from providers.provider_manager import get_last_provider_diagnostic, search_all_providers


def test_hybrid_manager_uses_demo_when_token_and_scrapers_are_disabled(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    monkeypatch.setenv("ENABLE_AIRLINE_SCRAPERS", "false")

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
    assert diagnostic["scrapers"][0]["status"] == "disabled"
    get_settings.cache_clear()
