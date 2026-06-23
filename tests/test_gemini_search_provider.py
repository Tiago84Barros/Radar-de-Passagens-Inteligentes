import json
from types import SimpleNamespace

import pytest

from providers.gemini_search_provider import GeminiSearchProvider, _extract_gemini_grounded_payload


SOURCE_URL = "https://www.skyscanner.com.br/transport/flights/gru/lis/260910/"


def _grounded(payload, source_url=SOURCE_URL, *, citation_url=None, title="Skyscanner"):
    text = payload
    try:
        items = json.loads(payload)
    except (TypeError, ValueError):
        items = None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item.setdefault("source_url", source_url)
                item.setdefault("fonte", title)
        text = json.dumps(items)
    return {
        "text": text,
        "citations": [{"url": citation_url or source_url, "title": title}],
    }


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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(VALID_JSON))

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
    grounded = _grounded(VALID_JSON)
    grounded["text"] = "```json\n" + grounded["text"] + "\n```"
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: grounded)

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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(payload))

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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(payload))

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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(payload))

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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(payload))

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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(payload))

    assert provider.search_flights("GRU", "LIS", "2026-09-10") == []


def test_only_accepts_specific_trusted_urls_present_in_native_citations(provider, monkeypatch):
    latam_url = "https://www.latamairlines.com/br/pt/oferta/gru-lis-2026-09-10"
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
                "source_url": latam_url,
            },
            {
                "companhia": "TAP",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1900.0,
                "source_url": "https://example.com/fake",
            },
        ]
    )
    monkeypatch.setattr(
        provider,
        "_call_gemini",
        lambda prompt: {
            "text": payload,
            "citations": [
                {"url": latam_url, "title": "LATAM"},
                {"url": "https://example.com/fake", "title": "Example"},
            ],
        },
    )

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert len(results) == 1
    assert results[0]["booking_link"] == latam_url
    assert results[0]["source_url"] == latam_url
    assert results[0]["source_verified"] is True


def test_search_flights_returns_empty_list_on_invalid_json(provider, monkeypatch):
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded("isso nao e json"))

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
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: _grounded(bad_payload))

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert len(results) == 1
    assert results[0]["airline"] == "TAP"


def test_discards_complete_looking_fare_without_native_citations(provider, monkeypatch):
    monkeypatch.setattr(provider, "_call_gemini", lambda prompt: {"text": VALID_JSON, "citations": []})

    assert provider.search_flights("GRU", "LIS", "2026-09-10", "2026-09-20") == []


def test_discards_source_url_not_present_in_citations(provider, monkeypatch):
    payload = json.dumps(
        [
            {
                "companhia": "LATAM",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
                "source_url": "https://www.latamairlines.com/br/pt/oferta/gru-lis",
            }
        ]
    )
    monkeypatch.setattr(
        provider,
        "_call_gemini",
        lambda prompt: {
            "text": payload,
            "citations": [{"url": SOURCE_URL, "title": "Skyscanner"}],
        },
    )

    assert provider.search_flights("GRU", "LIS", "2026-09-10") == []


def test_discards_generic_homepage_even_when_cited(provider, monkeypatch):
    homepage = "https://www.voegol.com.br/"
    payload = json.dumps(
        [
            {
                "companhia": "GOL",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
                "source_url": homepage,
            }
        ]
    )
    monkeypatch.setattr(
        provider,
        "_call_gemini",
        lambda prompt: {"text": payload, "citations": [{"url": homepage, "title": "GOL"}]},
    )

    assert provider.search_flights("GRU", "LIS", "2026-09-10") == []


def test_accepts_gemini_grounding_redirect_when_title_identifies_source(provider, monkeypatch):
    payload = json.dumps(
        [
            {
                "companhia": "TAP",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
                "source_url": SOURCE_URL,
            }
        ]
    )
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc123"
    monkeypatch.setattr(
        provider,
        "_call_gemini",
        lambda prompt: _grounded(
            payload,
            citation_url=redirect,
            title="Oferta de voo - skyscanner.com.br",
        ),
    )

    results = provider.search_flights("GRU", "LIS", "2026-09-10")

    assert len(results) == 1
    assert results[0]["source_url"] == SOURCE_URL
    assert results[0]["raw_payload"]["matched_citation_url"] == redirect


def test_extracts_only_grounding_chunks_used_by_gemini_supports():
    supported_web = SimpleNamespace(uri=SOURCE_URL, title="Skyscanner", domain="skyscanner.com.br")
    unused_web = SimpleNamespace(
        uri="https://www.example.com/not-used",
        title="Unused",
        domain="example.com",
    )
    metadata = SimpleNamespace(
        grounding_chunks=[
            SimpleNamespace(web=supported_web),
            SimpleNamespace(web=unused_web),
        ],
        grounding_supports=[
            SimpleNamespace(
                grounding_chunk_indices=[0],
                segment=SimpleNamespace(start_index=0, end_index=100),
            )
        ],
    )
    response = SimpleNamespace(
        text="[]",
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
    )

    grounded = _extract_gemini_grounded_payload(response)

    assert grounded["text"] == "[]"
    assert [item["url"] for item in grounded["citations"]] == [SOURCE_URL]
