from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.db import MonitoredSearch, TrackedFareState

# Only searches in this status are executed by the bot.
RUNNABLE_STATUS = "active"


def list_monitored_searches(db) -> list[MonitoredSearch]:
    return list(db.scalars(select(MonitoredSearch).order_by(MonitoredSearch.created_at.desc())))


def get_monitored_search(db, search_id: int) -> Optional[MonitoredSearch]:
    return db.get(MonitoredSearch, search_id)


def find_existing_monitor(db, origin_iata: str, destination_iata: str) -> Optional[MonitoredSearch]:
    """An active monitored search already covering this route, if any — used by
    the 'Rastrear esta busca 24h' replace-confirmation dialog."""
    return db.scalar(
        select(MonitoredSearch).where(
            MonitoredSearch.origin_iata == (origin_iata or "").upper(),
            MonitoredSearch.destination_iata == (destination_iata or "").upper(),
            MonitoredSearch.status == RUNNABLE_STATUS,
        )
    )


def create_monitored_search(db, config: dict) -> MonitoredSearch:
    """Persist ONLY the search configuration — never result history (spec)."""
    search = MonitoredSearch(
        status=RUNNABLE_STATUS,
        origin_iata=str(config.get("origin_iata") or "").upper(),
        origin_city=config.get("origin_city"),
        destination_iata=str(config.get("destination_iata") or "").upper(),
        destination_city=config.get("destination_city"),
        departure_date=_parse_date(config.get("departure_date")),
        return_date=_parse_date(config.get("return_date")),
        adults=int(config.get("adults") or 1),
        trip_type=config.get("trip_type") or "round_trip",
        max_price=_to_float(config.get("max_price")),
        consider_miles=bool(config.get("consider_miles", True)),
        min_mile_value=float(config.get("min_mile_value") or 0.035),
        max_stops=config.get("max_stops"),
        max_duration_minutes=config.get("max_duration_minutes"),
        search_window_days=int(config.get("search_window_days") or 1),
        telegram_enabled=bool(config.get("telegram_enabled", True)),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(search)
    db.flush()
    return search


def replace_monitored_search(db, existing: MonitoredSearch, config: dict) -> MonitoredSearch:
    """Replace an existing monitor for the same route with a fresh configuration —
    the 'Substituir' branch of the replace-confirmation dialog."""
    state = db.get(TrackedFareState, existing.id)
    if state:
        db.delete(state)
    db.delete(existing)
    db.flush()
    return create_monitored_search(db, config)


def set_status(db, search: MonitoredSearch, status: str) -> MonitoredSearch:
    search.status = status
    search.updated_at = datetime.now(timezone.utc)
    return search


def delete_monitored_search(db, search: MonitoredSearch) -> None:
    state = db.get(TrackedFareState, search.id)
    if state:
        db.delete(state)
    db.delete(search)


def record_run_result(
    db,
    search: MonitoredSearch,
    *,
    best_price: float | None,
    best_link: str | None,
    status_message: str | None,
    notified: bool = False,
) -> MonitoredSearch:
    """Update only the status-summary fields after a bot run — never history."""
    now = datetime.now(timezone.utc)
    search.last_checked_at = now
    search.updated_at = now
    if best_price is not None:
        search.last_best_price = float(best_price)
    if best_link:
        search.last_best_link = best_link
    if status_message:
        search.last_status_message = status_message
    if notified:
        search.last_notification_at = now
    return search


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
