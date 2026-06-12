import json

import pytest

from providers.gemini_search_provider import GeminiSearchProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-123")
    from app.settings import get_settings

    get_settings.cache_clear()
    yield GeminiSearchProvider()
    get_settings.cache_clear()


VALID_JSON = json.dumps(
    [
        {
            "companhia": "LATAM",
            "origem": "gru",
            "destino": "lis",
            "data_ida": "2026-09-10",
            "data_volta": "2026-09-20",
            "escalas": 0,
            "preco_brl": 3200.50,
            "link": "https://example.com/voo1",
            "fonte": "google flights",
        },
        {
            "companhia": "TAP",
            "origem": "gru",
            "destino": "lis",
            "data_ida": "2026-09-10",
            "data_volta": "2026-09-20",
            "escalas": 1,
            "preco_brl": 2800.00,
            "link": "https://example.com/voo2",
            "fonte": "tap.com",
        },
    ]
)


def test_is_configured_true_with_api_key(provider):
    assert provider.is_configured() is True


def test_search_flights_parses_mocked_response_and_sorts_by_price(provider, monkeypatch):
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: VALID_JSON)

    results = provider.search_flights("GRU", "LIS", "2026-09-10", "2026-09-20")

    assert len(results) == 2
    # ordenado por preco crescente
    assert results[0]["airline"] == "TAP"
    assert results[0]["price"] == 2800.00
    assert results[0]["origin"] == "GRU"
    assert results[0]["destination"] == "LIS"
    assert results[0]["provider"] == "gemini_web_search"
    assert results[1]["airline"] == "LATAM"


def test_search_flights_handles_markdown_fenced_json(provider, monkeypatch):
    fenced = "```json\n" + VALID_JSON + "\n```"
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: fenced)

    results = provider.search_flights("GRU", "LIS", "2026-09-10", "2026-09-20")

    assert len(results) == 2


def test_one_way_search_discards_round_trip_items(provider, monkeypatch):
    """Busca somente ida: itens com data_volta sao pacotes ida+volta (preco do
    pacote, nao do trecho) e devem ser descartados."""
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "data_volta": "2026-09-20",
                "preco_brl": 3200.50,
            },
            {
                "companhia": "TAP",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "data_volta": None,
                "preco_brl": 1800.00,
            },
        ]
    )
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: payload)

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert len(results) == 1
    assert results[0]["airline"] == "TAP"
    assert results[0]["return_date"] is None


def test_search_flights_returns_empty_list_on_invalid_json(provider, monkeypatch):
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: "isso nao e json")

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert results == []


def test_search_flights_returns_empty_list_when_not_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from app.settings import get_settings

    get_settings.cache_clear()
    try:
        provider = GeminiSearchProvider()
        assert provider.is_configured() is False
        assert provider.search_flights("GRU", "LIS", "2026-09-10") == []
    finally:
        get_settings.cache_clear()


def test_search_flights_skips_items_failing_schema_validation(provider, monkeypatch):
    bad_payload = json.dumps(
        [
            {"companhia": "LATAM", "origem": "GRU", "destino": "LIS", "data_ida": "2026-09-10", "preco_brl": -10},
            {"companhia": "TAP", "origem": "GRU", "destino": "LIS", "data_ida": "2026-09-10", "preco_brl": 1500.0},
        ]
    )
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: bad_payload)

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert len(results) == 1
    assert results[0]["airline"] == "TAP"
