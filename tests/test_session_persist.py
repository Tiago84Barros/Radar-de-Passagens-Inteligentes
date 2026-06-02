"""Auth token (reload persistence), query-param restore and worker auto-refresh
early-stop when new prices arrive."""
import importlib
import os
import tempfile
import time
from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

import streamlit_app as app


def test_auth_token_stable_and_secret():
    t1 = app._auth_token("hunter2")
    t2 = app._auth_token("hunter2")
    assert t1 == t2 and len(t1) == 32
    assert "hunter2" not in t1                 # non-reversible (no raw password)
    assert app._auth_token("other") != t1


@pytest.fixture()
def seeded_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    import app.settings as settings
    settings.get_settings.cache_clear()
    import app.db as db
    importlib.reload(db)
    db.init_db()
    yield db
    try:
        db.get_engine().dispose()
        os.remove(path)
    except Exception:
        pass


def _add_quote(db, origin="GRU", destination="GIG"):
    with db.session_scope() as s:
        s.add(db.FlightQuote(
            search_id=1, origin=origin, destination=destination,
            departure_date=date.today() + timedelta(days=30), airline="G3",
            price=500.0, booking_link="", provider="google",
        ))


def _app_with_poll(db, baseline):
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.session_state["worker_poll_until"] = time.time() + 200
    at.session_state["worker_route"] = ("GRU", "GIG")
    at.session_state["worker_baseline_count"] = baseline
    return at


def test_autorefresh_stops_when_new_prices_detected(seeded_db):
    db = seeded_db
    _add_quote(db); _add_quote(db)                 # baseline = 2
    at = _app_with_poll(db, baseline=2)
    _add_quote(db)                                 # worker writes a 3rd → new price
    at.run()
    assert not at.exception
    # Polling stopped early and a success banner is shown.
    assert "worker_poll_until" not in at.session_state
    assert any("Novos preços" in str(x.value) for x in at.success)


def test_autorefresh_continues_without_new_prices(seeded_db):
    db = seeded_db
    _add_quote(db); _add_quote(db)                 # baseline = 2, no new quote added
    at = _app_with_poll(db, baseline=2)
    at.run()
    assert not at.exception
    assert "worker_poll_until" in at.session_state                 # still polling
