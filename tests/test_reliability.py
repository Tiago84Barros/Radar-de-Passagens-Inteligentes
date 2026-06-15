"""Confiabilidade: Travelpayouts (preço real) é primário, IA só fallback, cada
oferta carimbada com source_confidence e o ranking favorece preço real."""
import providers.provider_manager as pm
from services.recommendation_service import rank_flight_options


class _FakeTP:
    def __init__(self, results):
        self._results = results

    def is_configured(self):
        return True

    def search_flights(self, **kw):
        return list(self._results)


def _tp_offer(price=2500.0):
    return {
        "provider": "travelpayouts", "source": "travelpayouts",
        "origin": "BEL", "destination": "FOR", "departure_date": "2026-09-10",
        "return_date": None, "airline": "LA", "price": price, "currency": "BRL", "stops": 0,
    }


def _base_params(**extra):
    p = {
        "origin": "BEL", "destination": "FOR", "departure_date": "2026-09-10",
        "return_date": None, "currency": "BRL", "max_connection_hubs": 0, "date_flex_days": 0,
    }
    p.update(extra)
    return p


def _spy_ai(monkeypatch, gemini_out=([], "nao_configurado"), openai_out=([], "nao_configurado")):
    called = []

    def fake_gemini(params):
        called.append("gemini")
        return gemini_out

    def fake_openai(params):
        called.append("openai")
        return openai_out

    monkeypatch.setattr(pm, "_search_gemini", fake_gemini)
    monkeypatch.setattr(pm, "_search_openai", fake_openai)
    return called


def test_travelpayouts_primary_skips_ai_when_real_price_exists(monkeypatch):
    monkeypatch.setattr(pm, "TravelPayoutsProvider", lambda: _FakeTP([_tp_offer()]))
    called = _spy_ai(monkeypatch)

    results = pm.search_all_providers(_base_params())

    assert called == []  # IA NÃO consultada — já há preço real
    assert results and results[0]["source_confidence"] == "real"


def test_force_web_search_runs_ai_even_with_real_price(monkeypatch):
    monkeypatch.setattr(pm, "TravelPayoutsProvider", lambda: _FakeTP([_tp_offer()]))
    called = _spy_ai(monkeypatch)

    pm.search_all_providers(_base_params(force_web_search=True))

    assert "gemini" in called and "openai" in called


def test_ai_used_as_fallback_when_no_real_price(monkeypatch):
    monkeypatch.setattr(pm, "TravelPayoutsProvider", lambda: _FakeTP([]))  # TP vazio
    gem = [{
        "provider": "gemini_web_search", "source": "gemini_web_search",
        "origin": "BEL", "destination": "FOR", "departure_date": "2026-09-10",
        "return_date": None, "airline": "G3", "price": 1800.0, "currency": "BRL", "stops": 0,
    }]
    called = _spy_ai(monkeypatch, gemini_out=(gem, "ok"))

    results = pm.search_all_providers(_base_params())

    assert "gemini" in called  # sem preço real → IA entra
    assert results and results[0]["source_confidence"] == "unverified"


def test_ranking_prefers_real_over_unverified_at_same_price():
    ai = {"price_brl": 1000.0, "duration_minutes": 120, "stops": 0, "airline": "G3", "source_confidence": "unverified"}
    real = {"price_brl": 1000.0, "duration_minutes": 120, "stops": 0, "airline": "LA", "source_confidence": "real"}
    ranking = rank_flight_options([ai, real], {"sort_by": "recomendados"})
    assert ranking["recommended_option"]["source_confidence"] == "real"


def test_ranking_penalizes_separate_ticket():
    direct = {"price_brl": 1000.0, "duration_minutes": 120, "stops": 0, "airline": "LA", "source_confidence": "real"}
    combo = {"price_brl": 1000.0, "duration_minutes": 120, "stops": 1, "airline": "LA+G3",
             "source_confidence": "real", "separate_ticket": True, "connection_risk": "alto"}
    ranking = rank_flight_options([combo, direct], {"sort_by": "recomendados"})
    assert ranking["recommended_option"].get("separate_ticket") is not True
