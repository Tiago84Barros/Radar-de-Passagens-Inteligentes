"""Operational control of monitored searches (the "Buscas Monitoradas" tab).

Each action is a simple, reversible state change on ``monitored_searches``. No
history is recorded — the table holds only configuration plus a status summary
(spec: sem banco historico). The bot reads the same table to decide what to run.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db import MonitoredSearch, session_scope
from services.database_service import (
    create_monitored_search,
    delete_monitored_search,
    get_monitored_search,
)

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"


def _touch(search: MonitoredSearch) -> None:
    search.updated_at = datetime.now(timezone.utc)


def pause_search(search_id: int) -> bool:
    with session_scope() as db:
        s = get_monitored_search(db, search_id)
        if not s:
            return False
        s.status = STATUS_PAUSED
        _touch(s)
        return True


def resume_search(search_id: int) -> bool:
    with session_scope() as db:
        s = get_monitored_search(db, search_id)
        if not s:
            return False
        s.status = STATUS_ACTIVE
        _touch(s)
        return True


def delete_search(search_id: int) -> bool:
    with session_scope() as db:
        s = get_monitored_search(db, search_id)
        if not s:
            return False
        delete_monitored_search(db, s)
        return True


def replace_search(search_id: int, config: dict) -> int | None:
    """Delete the current monitor and create a fresh one with ``config``."""
    with session_scope() as db:
        s = get_monitored_search(db, search_id)
        if not s:
            return None
        delete_monitored_search(db, s)
        db.flush()
        new = create_monitored_search(db, config)
        return new.id


def run_now(search_id: int) -> dict:
    """Execute this monitored search immediately and update its status summary."""
    from services.monitoring_bot import execute_monitored_search

    with session_scope() as db:
        s = get_monitored_search(db, search_id)
        if not s:
            return {"ok": False, "message": "Busca monitorada não encontrada."}
        result = execute_monitored_search(db, s)
        return {
            "ok": result.get("ok", False),
            "message": result.get("message") or "Busca executada.",
        }


# ── Read helpers for the UI ──────────────────────────────────────────────────

def list_monitored() -> list[dict]:
    """All monitored searches (newest first), as plain detached snapshots."""
    with session_scope() as db:
        rows = list(db.scalars(select(MonitoredSearch).order_by(MonitoredSearch.created_at.desc())))
        return [_snapshot(s) for s in rows]


def _snapshot(s: MonitoredSearch) -> dict:
    return {
        "id": s.id,
        "status": s.status,
        "origin_iata": s.origin_iata,
        "origin_city": s.origin_city,
        "destination_iata": s.destination_iata,
        "destination_city": s.destination_city,
        "departure_date": s.departure_date,
        "return_date": s.return_date,
        "adults": s.adults,
        "trip_type": s.trip_type,
        "max_price": s.max_price,
        "consider_miles": s.consider_miles,
        "min_mile_value": s.min_mile_value,
        "telegram_enabled": s.telegram_enabled,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "last_checked_at": s.last_checked_at,
        "last_notification_at": s.last_notification_at,
        "last_best_price": s.last_best_price,
        "last_best_link": s.last_best_link,
        "last_status_message": s.last_status_message,
    }
