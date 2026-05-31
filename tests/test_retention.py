"""Tests for DB retention: prune only old SUPERSEDED snapshots, keep the rest."""
import importlib
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture()
def fresh_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    import app.settings as settings
    settings.get_settings.cache_clear()
    import app.db as db
    importlib.reload(db)
    import services.database_service as ds
    importlib.reload(ds)
    db.init_db()
    yield db, ds
    try:
        db.get_engine().dispose()
        os.remove(path)
    except Exception:
        pass


def _add_quote(db, *, is_current, age_days, price=500.0):
    ts = datetime.now(timezone.utc) - timedelta(days=age_days)
    with db.session_scope() as s:
        q = db.FlightQuote(
            search_id=1, origin="GRU", destination="GIG",
            departure_date=date.today() + timedelta(days=30),
            airline="GOL", price=price, booking_link="", provider="travelpayouts",
            is_current=is_current,
        )
        s.add(q)
        s.flush()
        # Force the timestamp (server_default would otherwise be "now").
        q.detected_at = ts
        return q.id


def test_prune_removes_only_old_superseded(fresh_db):
    db, ds = fresh_db
    old_superseded = _add_quote(db, is_current=False, age_days=120)
    recent_superseded = _add_quote(db, is_current=False, age_days=10)
    old_current = _add_quote(db, is_current=True, age_days=200)

    with db.session_scope() as s:
        result = ds.prune_old_quotes(s, keep_days=90)

    assert result["quotes_deleted"] == 1
    from sqlalchemy import select
    with db.session_scope() as s:
        remaining = {q.id for q in s.scalars(select(db.FlightQuote))}
    assert old_superseded not in remaining          # removed
    assert recent_superseded in remaining           # kept (within window)
    assert old_current in remaining                 # kept (current price, any age)


def test_prune_noop_when_nothing_old(fresh_db):
    db, ds = fresh_db
    _add_quote(db, is_current=False, age_days=5)
    with db.session_scope() as s:
        result = ds.prune_old_quotes(s, keep_days=90)
    assert result["quotes_deleted"] == 0
