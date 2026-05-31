"""Tests for the Controle de Buscas control layer and worker eligibility."""
import os
import tempfile
import importlib

import pytest


@pytest.fixture()
def fresh_db(monkeypatch):
    """Isolated SQLite DB per test, with all app modules rebound to it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")

    import app.settings as settings
    settings.get_settings.cache_clear()
    import app.db as db
    importlib.reload(db)
    # Rebind modules that captured app.db symbols at import time.
    import services.monitoring_service as ms
    importlib.reload(ms)
    import services.search_control_service as scs
    importlib.reload(scs)

    db.init_db()
    yield db, ms, scs

    try:
        db.get_engine().dispose()
        os.remove(path)
    except Exception:
        pass


def _make_search(db, ms, **overrides):
    from datetime import date, timedelta
    params = dict(
        owner_email="demo@radar.local", origin="GRU", destination="GIG",
        departure_date=date.today() + timedelta(days=30), max_price=2000.0,
        currency="BRL", adults=1, passengers=1, frequency_minutes=60,
        is_active=True, status="active",
    )
    params.update(overrides)
    with db.session_scope() as s:
        fs = db.FlightSearch(**params)
        s.add(fs)
        s.flush()
        return fs.id


def _eligible_ids(db, ms, force=True):
    with db.session_scope() as s:
        return {x.id for x in ms.get_searches_to_run(s, force=force)}


def test_active_search_is_runnable(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms)
    assert sid in _eligible_ids(db, ms)
    assert any(x.id == sid for x in scs.list_searches())


def test_pause_removes_from_worker(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms)
    assert scs.pause_search(sid)
    assert sid not in _eligible_ids(db, ms)


def test_resume_restores(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms)
    scs.pause_search(sid)
    assert scs.resume_search(sid)
    assert sid in _eligible_ids(db, ms)


def test_soft_delete_hides_and_excludes(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms)
    assert scs.delete_search(sid)
    assert sid not in _eligible_ids(db, ms)
    assert all(x.id != sid for x in scs.list_searches())          # hidden by default
    assert any(x.id == sid for x in scs.list_searches(include_deleted=True))


def test_expired_search_ignored(fresh_db):
    from datetime import date, timedelta
    db, ms, scs = fresh_db
    sid = _make_search(db, ms, departure_date=date.today() - timedelta(days=1))
    assert sid not in _eligible_ids(db, ms)


def test_run_now_saves_and_logs(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms)
    result = scs.run_now(sid)
    assert result["ok"] and result["saved"] > 0
    assert scs.get_run_logs(sid), "a run log should be recorded"
    # last_run_at / next_run_at populated
    snap = next(x for x in scs.list_searches() if x.id == sid)
    assert snap.last_run_at is not None and snap.next_run_at is not None


def test_frequency_and_telegram_actions_logged(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms)
    scs.set_frequency(sid, 180)
    scs.set_telegram(sid, False)
    actions = {a["action"] for a in scs.get_action_logs(sid)}
    assert {"update_frequency", "update_telegram"} <= actions


def _alert_count(db, search_id):
    from sqlalchemy import func, select
    return db.scalar(
        select(func.count()).select_from(db_alertlog()).where(db_alertlog().search_id == search_id)
    )


def db_alertlog():
    from app.db import AlertLog
    return AlertLog


def test_telegram_disabled_suppresses_alerts(fresh_db):
    db, ms, scs = fresh_db
    # High max_price so every demo offer is alert-worthy; telegram OFF.
    sid = _make_search(db, ms, max_price=99999.0, telegram_enabled=False)
    scs.run_now(sid)
    with db.session_scope() as s:
        assert _alert_count(s, sid) == 0, "no alert should be logged when telegram is off"


def test_telegram_enabled_allows_alerts(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms, max_price=99999.0, telegram_enabled=True)
    scs.run_now(sid)
    with db.session_scope() as s:
        assert _alert_count(s, sid) > 0, "alerts should be logged when telegram is on"


def test_duplicate_creates_new_active(fresh_db):
    db, ms, scs = fresh_db
    sid = _make_search(db, ms, destination="ANYWHERE", search_type="multi",
                       area_scope="Exterior")
    new_id = scs.duplicate_search(sid)
    assert new_id and new_id != sid
    clone = next(x for x in scs.list_searches() if x.id == new_id)
    assert clone.status == "active" and clone.area_scope == "Exterior"
