"""Verify the Início flow: nothing searches until 'Buscar agora', simplified nav."""
import os
import tempfile

import pytest

from streamlit.testing.v1 import AppTest


@pytest.fixture()
def app(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    import app.settings as settings
    settings.get_settings.cache_clear()
    import app.db as db
    import importlib
    importlib.reload(db)
    db.init_db()
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.session_state["search_mode"] = "Rota específica"
    at.session_state["home_origin"] = {"code": "BEL", "label": "Belém (BEL)"}
    at.session_state["home_destination"] = {"code": "NYC", "label": "Nova York (NYC)"}
    at.session_state["radar_prefs"] = {
        "consider_miles": True, "min_mile_value": 0.035, "max_price": 3000.0,
        "scope": "ambos", "area_scope": "Ambos", "brazil_regions": [],
        "international_regions": [], "travel_window_days": 90,
    }
    yield at
    try:
        db.get_engine().dispose()
        os.remove(path)
    except Exception:
        pass


def test_no_results_until_search_clicked(app):
    """With origin+destination selected but no search executed, no results show."""
    app.run()
    assert not app.exception
    md = " ".join(str(m.value) for m in app.markdown)
    # Results sections must NOT appear before clicking Buscar agora.
    assert "Opções encontradas" not in md
    assert "Andamento da execu" not in md


def test_navigation_is_simplified(app):
    app.run()
    assert len(app.tabs) == 3                      # Início, Controle de Buscas, Configurações
    radio_labels = " ".join((r.label or "") for r in app.radio).lower()
    assert "coletadas" not in radio_labels         # no "tarifas coletadas nas últimas" radio


def test_sidebar_has_only_buscar_agora(app):
    app.run()
    labels = [b.label or "" for b in app.button]
    assert not any("Iniciar monitor" in l for l in labels)
    assert not any("Rodar buscas" in l for l in labels)
    assert any("Buscar agora" in l for l in labels)
