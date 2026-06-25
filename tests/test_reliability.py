"""Confiabilidade: tarifas do motor principal vêm apenas de APIs configuradas."""

import providers.provider_manager as pm
from services.recommendation_service import rank_flight_options


class _FakeProvider:
    def __init__(self, results, configured=True):
        self._results = results
        self._configured = configured

    def is_configured(self):
        return self._configured

    def search_flights(self, **kw):
        return list(self._results)

    def search_flexible_dates(self, **kw):
        return []


def _offer(provider="travelpayouts", price=2500.0, departure_date="2026-09-10", return_date=None):
    return {
        "provider": provider,
        "source": provider,
        "origin": "BEL",
        "destination": "FOR",
        "departure_date": departure_date,
        "return_date": return_date,
        "airline": "LA",
        "price": price,
        "currency": "BRL",
        "stops": 0,
        "booking_link": "https://example.com/search",
    }


def _base_params(**extra):
    p = {
        "origin": "BEL",
        "destination": "FOR",
        "departure_date": "2026-09-10",
        "return_date": None,
        "currency": "BRL",
        "max_connection_hubs": 0,
        "date_flex_days": 0,
    }
    p.update(extra)
    return p


def _patch_providers(monkeypatch, serpapi_results=None, tp_results=None, *, configured=True):
    monkeypatch.setattr(
        pm,
        "SerpApiGoogleFlightsProvider",
        lambda: _FakeProvider(serpapi_results or [], configured=configured),
    )
    monkeypatch.setattr(
        pm,
        "TravelPayoutsProvider",
        lambda: _FakeProvider(tp_results or [], configured=configured),
    )


def test_serpapi_and_travelpayouts_results_are_real_sources(monkeypatch):
    _patch_providers(
        monkeypatch,
        serpapi_results=[_offer("serpapi_google_flights", 1800.0)],
        tp_results=[_offer("travelpayouts", 1900.0)],
    )

    results = pm.search_all_providers(_base_params())

    assert [r["provider"] for r in results] == ["serpapi_google_flights", "travelpayouts"]
    assert all(r["source_confidence"] == "real" for r in results)
    assert pm.get_last_provider_diagnostic()["status"] == "api_ok"


def test_force_web_search_does_not_enable_llm_fallback(monkeypatch):
    _patch_providers(monkeypatch, tp_results=[_offer("travelpayouts")])

    results = pm.search_all_providers(_base_params(force_web_search=True))

    assert len(results) == 1
    assert results[0]["provider"] == "travelpayouts"
    assert "gemini" not in pm.get_last_provider_diagnostic()
    assert "openai" not in pm.get_last_provider_diagnostic()


def test_no_configured_api_returns_no_fares(monkeypatch):
    _patch_providers(monkeypatch, configured=False)

    results = pm.search_all_providers(_base_params())

    assert results == []
    diagnostic = pm.get_last_provider_diagnostic()
    assert diagnostic["status"] == "no_confirmed_source"
    assert "SERPAPI_API_KEY" in diagnostic["message"]


def test_api_fare_outside_date_tolerance_is_rejected(monkeypatch):
    _patch_providers(
        monkeypatch,
        serpapi_results=[_offer("serpapi_google_flights", departure_date="2026-07-15")],
        tp_results=[],
    )

    results = pm.search_all_providers(_base_params(departure_date="2026-07-31", date_flex_days=5))

    assert results == []
    assert pm.get_last_provider_diagnostic()["status"] == "no_confirmed_source"


def test_return_leg_before_outbound_date_is_rejected(monkeypatch):
    _patch_providers(
        monkeypatch,
        serpapi_results=[_offer("serpapi_google_flights", departure_date="2026-07-15")],
    )

    results = pm.search_all_providers(
        _base_params(
            departure_date="2026-07-31",
            date_flex_days=15,
            min_departure_date="2026-07-24",
        )
    )

    assert results == []


def test_fare_inside_date_tolerance_is_kept(monkeypatch):
    _patch_providers(
        monkeypatch,
        serpapi_results=[_offer("serpapi_google_flights", departure_date="2026-08-03")],
    )

    results = pm.search_all_providers(_base_params(departure_date="2026-07-31", date_flex_days=5))

    assert len(results) == 1
    assert results[0]["departure_date"] == "2026-08-03"
    assert results[0]["source_confidence"] == "real"


def test_ranking_prefers_real_over_unverified_at_same_price():
    unverified = {
        "price_brl": 1000.0,
        "duration_minutes": 120,
        "stops": 0,
        "airline": "G3",
        "source_confidence": "unverified",
    }
    real = {
        "price_brl": 1000.0,
        "duration_minutes": 120,
        "stops": 0,
        "airline": "LA",
        "source_confidence": "real",
    }
    ranking = rank_flight_options([unverified, real], {"sort_by": "recomendados"})
    assert ranking["recommended_option"]["source_confidence"] == "real"


def test_ranking_penalizes_separate_ticket():
    direct = {"price_brl": 1000.0, "duration_minutes": 120, "stops": 0, "airline": "LA", "source_confidence": "real"}
    combo = {
        "price_brl": 1000.0,
        "duration_minutes": 120,
        "stops": 1,
        "airline": "LA+G3",
        "source_confidence": "real",
        "separate_ticket": True,
        "connection_risk": "alto",
    }
    ranking = rank_flight_options([combo, direct], {"sort_by": "recomendados"})
    assert ranking["recommended_option"].get("separate_ticket") is not True
