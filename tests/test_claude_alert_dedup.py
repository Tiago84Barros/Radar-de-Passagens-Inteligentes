"""End-to-end check that offers coming from the Claude web_search provider flow
through the existing dedup/alert pipeline correctly: alert fires when
preco <= alvo and the route hasn't been alerted recently, and does not repeat
for the same-or-worse price on a subsequent run (spec: cron de 4h nao deve
repetir o mesmo aviso)."""
import importlib
import os
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture()
def fresh_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    import app.settings as settings
    settings.get_settings.cache_clear()
    import app.db as db
    importlib.reload(db)
    import services.monitoring_service as ms
    importlib.reload(ms)

    db.init_db()
    yield db, ms

    try:
        db.get_engine().dispose()
        os.remove(path)
    except Exception:
        pass


def _make_search(db, **overrides):
    params = dict(
        owner_email="demo@radar.local", origin="GRU", destination="LIS",
        departure_date=date.today() + timedelta(days=60), max_price=3000.0,
        currency="BRL", adults=1, passengers=1, frequency_minutes=240,
        is_active=True, status="active", telegram_enabled=True,
    )
    params.update(overrides)
    with db.session_scope() as s:
        fs = db.FlightSearch(**params)
        s.add(fs)
        s.flush()
        return fs.id


def _claude_offer(price: float):
    return {
        "provider": "claude_web_search",
        "source": "claude_web_search",
        "origin": "GRU",
        "destination": "LIS",
        "departure_date": (date.today() + timedelta(days=60)).isoformat(),
        "return_date": None,
        "airline": "TAP",
        "price": price,
        "currency": "BRL",
        "duration_minutes": None,
        "stops": 1,
        "booking_link": "https://example.com/voo",
        "raw_payload": {"claude_web_search": True},
    }


def _sent_alert_count(db, search_id):
    from app.db import AlertLog

    with db.session_scope() as s:
        return len(
            list(
                s.query(AlertLog).filter(
                    AlertLog.search_id == search_id,
                    AlertLog.channel == "telegram",
                    AlertLog.status == "sent",
                )
            )
        )


def test_alert_fires_when_claude_price_at_or_below_target(fresh_db, monkeypatch):
    db, ms = fresh_db
    sid = _make_search(db)

    monkeypatch.setattr(ms, "search_all_providers", lambda params: [_claude_offer(2500.0)])
    monkeypatch.setattr(ms, "search_year_price_calendar", lambda params: [])
    monkeypatch.setattr("app.alerts.send_telegram_message", lambda msg: (True, "ok"))

    with db.session_scope() as s:
        search = s.get(db.FlightSearch, sid)
        ms.run_search_once(s, search)

    assert _sent_alert_count(db, sid) == 1


def test_alert_does_not_repeat_for_same_or_worse_price(fresh_db, monkeypatch):
    db, ms = fresh_db
    sid = _make_search(db)

    monkeypatch.setattr(ms, "search_year_price_calendar", lambda params: [])
    monkeypatch.setattr("app.alerts.send_telegram_message", lambda msg: (True, "ok"))

    monkeypatch.setattr(ms, "search_all_providers", lambda params: [_claude_offer(2500.0)])
    with db.session_scope() as s:
        search = s.get(db.FlightSearch, sid)
        ms.run_search_once(s, search)

    # Segunda execucao do cron de 4h: mesmo preco (ou pior) para a mesma rota —
    # nao deve repetir o alerta.
    monkeypatch.setattr(ms, "search_all_providers", lambda params: [_claude_offer(2600.0)])
    with db.session_scope() as s:
        search = s.get(db.FlightSearch, sid)
        ms.run_search_once(s, search)

    assert _sent_alert_count(db, sid) == 1


def test_no_alert_when_claude_price_above_target(fresh_db, monkeypatch):
    db, ms = fresh_db
    sid = _make_search(db, max_price=2000.0)

    monkeypatch.setattr(ms, "search_all_providers", lambda params: [_claude_offer(2900.0)])
    monkeypatch.setattr(ms, "search_year_price_calendar", lambda params: [])
    monkeypatch.setattr("app.alerts.send_telegram_message", lambda msg: (True, "ok"))

    with db.session_scope() as s:
        search = s.get(db.FlightSearch, sid)
        ms.run_search_once(s, search)

    assert _sent_alert_count(db, sid) == 0
