from providers import provider_manager


SEARCH_PARAMS = {
    "origin": "GRU",
    "destination": "LIS",
    "departure_date": "2026-09-10",
    "return_date": "2026-09-20",
    "currency": "BRL",
    "adults": 1,
}


class _FakeConfiguredClaudeProvider:
    name = "claude_web_search"

    def is_configured(self):
        return True

    def search_flights(self, **kwargs):
        return [
            {
                "provider": "claude_web_search",
                "source": "claude_web_search",
                "origin": "GRU",
                "destination": "LIS",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "airline": "TAP",
                "price": 2750.0,
                "currency": "BRL",
                "duration_minutes": None,
                "stops": 1,
                "booking_link": "https://example.com/voo",
                "raw_payload": {"claude_web_search": True},
            }
        ]


class _FakeUnconfiguredClaudeProvider:
    name = "claude_web_search"

    def is_configured(self):
        return False

    def search_flights(self, **kwargs):  # pragma: no cover - nao deve ser chamado
        raise AssertionError("search_flights nao deveria ser chamado quando nao configurado")


def _patch_claude_provider(monkeypatch, fake_cls):
    import providers.claude_search_provider as csp

    monkeypatch.setattr(csp, "ClaudeSearchProvider", fake_cls)


def test_search_all_providers_includes_claude_results_when_configured(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    monkeypatch.setenv("ENABLE_AIRLINE_SCRAPERS", "false")
    _patch_claude_provider(monkeypatch, _FakeConfiguredClaudeProvider)

    from app.settings import get_settings

    get_settings.cache_clear()
    try:
        results = provider_manager.search_all_providers(dict(SEARCH_PARAMS))
        diagnostic = provider_manager.get_last_provider_diagnostic()

        claude_hits = [r for r in results if r.get("provider") == "claude_web_search"]
        assert claude_hits, "esperava ao menos uma cotacao do Claude web_search na lista combinada"
        assert claude_hits[0]["price"] == 2750.0
        assert "claude_web_search" in diagnostic
    finally:
        get_settings.cache_clear()


def test_search_all_providers_skips_claude_when_not_configured(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    monkeypatch.setenv("ENABLE_AIRLINE_SCRAPERS", "false")
    _patch_claude_provider(monkeypatch, _FakeUnconfiguredClaudeProvider)

    from app.settings import get_settings

    get_settings.cache_clear()
    try:
        results = provider_manager.search_all_providers(dict(SEARCH_PARAMS))

        claude_hits = [r for r in results if r.get("provider") == "claude_web_search"]
        assert claude_hits == []
    finally:
        get_settings.cache_clear()
