"""Tests for the search summary card and execution-progress panel.

These capture the HTML/markdown the components emit (by stubbing Streamlit) so we
verify content deterministically, without a full Streamlit runtime.
"""
import pytest


@pytest.fixture()
def captured(monkeypatch):
    import streamlit as st

    sink: list = []

    class _Col:
        def markdown(self, *a, **k):
            sink.append(a[0] if a else "")

    monkeypatch.setattr(st, "markdown", lambda *a, **k: sink.append(a[0] if a else ""))
    monkeypatch.setattr(st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(st, "divider", lambda *a, **k: None)
    monkeypatch.setattr(st, "columns", lambda n: [_Col() for _ in range(n if isinstance(n, int) else len(n))])
    monkeypatch.setattr(st, "plotly_chart", lambda *a, **k: sink.append("PLOTLY_FIGURE"))
    return sink


_DEALS = [
    {"airline": "G3", "price_brl": 480.0, "estimated_miles": 13500, "provider": "travelpayouts", "score": 72},
    {"airline": "AD", "price_brl": 520.0, "provider": "travelpayouts", "score": 60},
    {"airline": "LA", "price_brl": 610.0, "provider": "travelpayouts", "score": 80},
]
_PROGRESS = {
    "origin_code": "GRU", "destination_code": "GIG", "api_seconds": 2.3, "trigger_seconds": 0.4,
    "worker_status": "queued", "worker_estimate_seconds": 90, "saved": 3, "started_at": 0,
}


def test_search_summary_shows_full_airlines_and_fields(captured):
    from components.decision_cards import render_search_summary

    render_search_summary(_DEALS, {"recommendation": "Comprar agora"}, route="GRU → GIG", progress=_PROGRESS)
    html = " ".join(captured)
    assert "Resumo da busca" in html
    assert "Companhias encontradas" in html
    # Full airline names, not IATA codes:
    for full in ("GOL Linhas Aéreas", "Azul Linhas Aéreas", "LATAM Airlines"):
        assert full in html
    assert "R$ 480,00" in html            # cheapest price
    assert "Comprar agora" in html        # recommendation


def test_search_summary_empty_deals_renders_nothing(captured):
    from components.decision_cards import render_search_summary

    render_search_summary([], {"recommendation": "Aguardar"}, route="GRU → GIG")
    assert not captured


def test_execution_progress_panel_and_bar_chart(captured):
    from components.progress import render_execution_progress

    render_execution_progress(_PROGRESS)
    html = " ".join(str(c) for c in captured)
    assert "Andamento da execu" in html       # section header
    assert "PLOTLY_FIGURE" in captured        # per-step bar chart
    assert "Na fila" in html                  # worker status label
