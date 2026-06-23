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


def test_discards_implausible_low_prices(provider, monkeypatch):
    """Valores absurdos (R$ 1,90 = alucinacao de escala) sao descartados; a
    tarifa real e o preco em milhas valido sobrevivem."""
    payload = json.dumps([
        {"companhia": "Avianca", "origem": "bel", "destino": "jfk", "data_ida": "2026-12-14",
         "preco_brl": 1.90, "milhas": {"programa": "LifeMiles", "quantidade": 35, "taxas_brl": 150.0},
         "link": "https://example.com/a", "fonte": "x"},
        {"companhia": "LATAM", "origem": "bel", "destino": "jfk", "data_ida": "2026-12-14",
         "preco_brl": 4200.00, "milhas": {"programa": "Latam Pass", "quantidade": 40, "taxas_brl": 180.0},
         "link": "https://example.com/b", "fonte": "y"},
    ])
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: payload)

    results = provider.search_flights("BEL", "JFK", "2026-12-14")

    # A oferta de R$ 1,90 some; sobra a de R$ 4.200.
    assert len(results) == 1
    assert results[0]["airline"] == "LATAM"
    assert results[0]["price"] == 4200.00
    # Milhas implausiveis (40) sao ignoradas — sem miles_offer.
    assert results[0].get("miles_offer") is None


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


def test_one_way_search_salvages_outbound_price_from_round_trip_breakdown(provider, monkeypatch):
    """Busca somente ida: pacote ida+volta COM detalhamento de preco da ida e
    aproveitado como tarifa one-way (preco so do trecho, sem data de volta)."""
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "data_volta": "2026-09-20",
                "preco_total_brl": 4000.00,
                "preco_ida_brl": 1900.00,
                "preco_volta_brl": 2100.00,
            },
        ]
    )
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: payload)

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert len(results) == 1
    assert results[0]["price"] == 1900.00
    assert results[0]["return_date"] is None
    assert results[0]["price_return"] is None


def test_revalidates_salvaged_one_way_price(provider, monkeypatch):
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "data_volta": "2026-09-20",
                "preco_total_brl": 4000.00,
                "preco_ida_brl": 1.90,
                "preco_volta_brl": 3998.10,
            }
        ]
    )
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: payload)

    assert provider.search_flights("GRU", "LIS", "2026-09-10") == []


def test_discards_route_or_date_that_does_not_match_request(provider, monkeypatch):
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "MAD",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
            },
            {
                "companhia": "TAP",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-20",
                "preco_brl": 1900.0,
            },
        ]
    )
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: payload)

    assert provider.search_flights("GRU", "LIS", "2026-09-10") == []


def test_only_exposes_links_from_known_official_airline_domains(provider, monkeypatch):
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
                "link": "https://latamairlines.com/br/pt",
            },
            {
                "companhia": "TAP",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1900.0,
                "link": "https://example.com/fake",
            },
        ]
    )
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: payload)

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert results[0]["booking_link"].startswith("https://latamairlines.com")
    assert results[1]["booking_link"] == ""
    assert results[1]["raw_payload"]["link_rejected"] is True


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
