"""Operational control of scheduled searches (the 'Controle de Buscas' panel).

Every action is a soft, reversible state change on ``flight_searches`` plus an
audit row in ``search_action_logs``. Nothing here deletes historical quotes or
alerts. The worker keeps reading via ``monitoring_service.get_searches_to_run``,
so pausing/deleting here immediately removes a search from the worker's scope.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db import (
    FlightSearch,
    SearchActionLog,
    SearchRunLog,
    session_scope,
)
from services.monitoring_service import effective_status, execute_search, is_expired

# Status constants (single source of truth for the UI and worker).
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_DELETED = "deleted"
STATUS_ERROR = "error"
STATUS_COMPLETED = "completed"


def _log_action(db, search: FlightSearch, action: str, previous: str, new: str, message: str | None = None) -> None:
    db.add(
        SearchActionLog(
            search_id=search.id,
            action=action,
            previous_status=previous,
            new_status=new,
            message=message,
        )
    )


def _touch(search: FlightSearch) -> None:
    search.updated_at = datetime.now(timezone.utc)


def pause_search(search_id: int) -> bool:
    """Pause a search: status=paused, is_active=False (worker ignores it)."""
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return False
        prev = effective_status(s)
        s.status = STATUS_PAUSED
        s.is_active = False
        s.paused_at = datetime.now(timezone.utc)
        _touch(s)
        _log_action(db, s, "pause", prev, STATUS_PAUSED)
        return True


def resume_search(search_id: int) -> bool:
    """Reactivate a search: status=active, is_active=True, updated_at refreshed."""
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return False
        prev = effective_status(s)
        s.status = STATUS_ACTIVE
        s.is_active = True
        s.paused_at = None
        s.last_error = None
        _touch(s)
        _log_action(db, s, "resume", prev, STATUS_ACTIVE)
        return True


def delete_search(search_id: int) -> bool:
    """Soft-delete: status=deleted, is_active=False, deleted_at set. Historical
    quotes and alerts are preserved; the worker ignores it."""
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return False
        prev = effective_status(s)
        s.status = STATUS_DELETED
        s.is_active = False
        s.deleted_at = datetime.now(timezone.utc)
        _touch(s)
        _log_action(db, s, "delete", prev, STATUS_DELETED)
        return True


def set_frequency(search_id: int, frequency_minutes: int) -> bool:
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return False
        old = s.frequency_minutes
        s.frequency_minutes = int(frequency_minutes)
        _touch(s)
        _log_action(db, s, "update_frequency", effective_status(s), effective_status(s),
                    f"{old}min → {frequency_minutes}min")
        return True


def set_telegram(search_id: int, enabled: bool) -> bool:
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return False
        s.telegram_enabled = bool(enabled)
        _touch(s)
        _log_action(db, s, "update_telegram", effective_status(s), effective_status(s),
                    "Telegram ligado" if enabled else "Telegram desligado")
        return True


def run_now(search_id: int) -> dict:
    """Execute ONLY this search immediately (spec §5/§18). Records run logs and
    control fields. Returns a small result summary for the UI."""
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return {"ok": False, "message": "Busca não encontrada."}
        prev = effective_status(s)
        saved = execute_search(db, s, source="manual")
        _log_action(db, s, "run_now", prev, effective_status(s), f"{saved} cotação(ões) salvas")
        return {
            "ok": s.last_status != "error",
            "saved": saved,
            "status": s.last_status,
            "error": s.last_error,
            "message": (
                f"✅ Busca executada: {saved} cotação(ões) salvas."
                if s.last_status != "error"
                else f"⚠️ Erro ao executar: {s.last_error}"
            ),
        }


def duplicate_search(search_id: int) -> int | None:
    """Create a new active search with the same parameters (spec §17). Dates are
    copied as-is; the user can adjust them afterwards."""
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s:
            return None
        clone = FlightSearch(
            owner_email=s.owner_email,
            origin=s.origin,
            destination=s.destination,
            departure_date=s.departure_date,
            return_date=s.return_date,
            flexible_dates=s.flexible_dates,
            adults=s.adults,
            passengers=s.passengers,
            max_price=s.max_price,
            currency=s.currency,
            trip_type=s.trip_type,
            baggage_included=s.baggage_included,
            frequency_minutes=s.frequency_minutes,
            is_active=True,
            status=STATUS_ACTIVE,
            search_type=s.search_type,
            area_scope=s.area_scope,
            brazil_regions=s.brazil_regions,
            international_regions=s.international_regions,
            candidate_destinations=s.candidate_destinations,
            telegram_enabled=s.telegram_enabled,
            consider_miles=s.consider_miles,
            min_mile_value=s.min_mile_value,
        )
        db.add(clone)
        db.flush()
        _log_action(db, clone, "duplicate", None, STATUS_ACTIVE, f"Duplicada da busca #{search_id}")
        return clone.id


def mark_completed_if_expired(search_id: int) -> bool:
    """Flag an expired specific-route search as completed (spec §16)."""
    with session_scope() as db:
        s = db.get(FlightSearch, search_id)
        if not s or not is_expired(s):
            return False
        prev = effective_status(s)
        s.status = STATUS_COMPLETED
        s.is_active = False
        _touch(s)
        _log_action(db, s, "complete", prev, STATUS_COMPLETED, "Data de ida expirada")
        return True


# ── Read helpers for the UI ──────────────────────────────────────────────────

def list_searches(include_deleted: bool = False) -> list[FlightSearch]:
    """All searches (newest first). Deleted ones are hidden unless requested."""
    with session_scope() as db:
        rows = list(db.scalars(select(FlightSearch).order_by(FlightSearch.created_at.desc())))
        # Detach lightweight snapshots so the caller can read after the session.
        result = []
        for s in rows:
            if not include_deleted and effective_status(s) == STATUS_DELETED:
                continue
            result.append(_snapshot(s))
        return result


def get_run_logs(search_id: int, limit: int = 10) -> list[dict]:
    with session_scope() as db:
        rows = db.scalars(
            select(SearchRunLog)
            .where(SearchRunLog.search_id == search_id)
            .order_by(SearchRunLog.started_at.desc())
            .limit(limit)
        )
        return [
            {
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "quotes_found": r.quotes_found,
                "best_price": r.best_price,
                "recommendation": r.recommendation,
                "error_message": r.error_message,
                "source": r.source,
            }
            for r in rows
        ]


def alert_counts() -> dict[int, int]:
    """Number of alert_logs per search_id (for the control table)."""
    from sqlalchemy import func as _func

    from app.db import AlertLog

    with session_scope() as db:
        rows = db.execute(
            select(AlertLog.search_id, _func.count()).group_by(AlertLog.search_id)
        ).all()
        return {int(sid): int(cnt) for sid, cnt in rows if sid is not None}


def latest_quotes_for_search(search_id: int, limit: int = 8) -> list[dict]:
    """Most recent quotes collected for a search (for 'Ver últimos resultados')."""
    from app.db import FlightQuote

    with session_scope() as db:
        rows = db.scalars(
            select(FlightQuote)
            .where(FlightQuote.search_id == search_id)
            .order_by(FlightQuote.detected_at.desc())
            .limit(limit)
        )
        return [
            {
                "origin": q.origin,
                "destination": q.destination,
                "airline": q.airline,
                "price": q.price,
                "departure_date": q.departure_date,
                "provider": q.provider,
                "opportunity": q.opportunity,
                "collected_at": q.collected_at or q.detected_at,
            }
            for q in rows
        ]


def alerts_for_search(search_id: int, limit: int = 10) -> list[dict]:
    """Alert logs related to a search (for 'Ver alertas enviados')."""
    from app.db import AlertLog

    with session_scope() as db:
        rows = db.scalars(
            select(AlertLog)
            .where(AlertLog.search_id == search_id)
            .order_by(AlertLog.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "channel": a.channel,
                "status": a.status,
                "created_at": a.created_at,
                "message": a.message,
            }
            for a in rows
        ]


def get_action_logs(search_id: int, limit: int = 15) -> list[dict]:
    with session_scope() as db:
        rows = db.scalars(
            select(SearchActionLog)
            .where(SearchActionLog.search_id == search_id)
            .order_by(SearchActionLog.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "action": r.action,
                "previous_status": r.previous_status,
                "new_status": r.new_status,
                "message": r.message,
                "created_at": r.created_at,
            }
            for r in rows
        ]


def _snapshot(s: FlightSearch) -> "SearchSnapshot":
    return SearchSnapshot(
        id=s.id,
        status=effective_status(s),
        expired=is_expired(s),
        search_type=s.search_type or ("multi" if str(s.destination).upper() == "ANYWHERE" else "route"),
        origin=s.origin,
        destination=s.destination,
        departure_date=s.departure_date,
        return_date=s.return_date,
        max_price=s.max_price,
        currency=s.currency,
        frequency_minutes=s.frequency_minutes,
        telegram_enabled=bool(getattr(s, "telegram_enabled", True)),
        consider_miles=bool(getattr(s, "consider_miles", True)),
        min_mile_value=float(getattr(s, "min_mile_value", 0.035) or 0.035),
        area_scope=s.area_scope,
        brazil_regions=s.brazil_regions,
        international_regions=s.international_regions,
        candidate_destinations=s.candidate_destinations,
        last_run_at=s.last_run_at,
        next_run_at=s.next_run_at,
        last_status=s.last_status,
        last_error=s.last_error,
        is_active=bool(s.is_active),
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


class SearchSnapshot:
    """Plain detached view of a FlightSearch for the UI (safe after session close)."""

    __slots__ = (
        "id", "status", "expired", "search_type", "origin", "destination",
        "departure_date", "return_date", "max_price", "currency", "frequency_minutes",
        "telegram_enabled", "consider_miles", "min_mile_value", "area_scope",
        "brazil_regions", "international_regions", "candidate_destinations",
        "last_run_at", "next_run_at", "last_status", "last_error", "is_active",
        "created_at", "updated_at",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}
