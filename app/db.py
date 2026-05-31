from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, create_engine, func, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


class FlightSearch(Base):
    __tablename__ = "flight_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_email: Mapped[str] = mapped_column(String(255), default="demo@radar.local", index=True)
    origin: Mapped[str] = mapped_column(String(8), index=True)
    destination: Mapped[str] = mapped_column(String(32), index=True, default="ANYWHERE")
    departure_date: Mapped[datetime] = mapped_column(Date)
    return_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    flexible_dates: Mapped[bool] = mapped_column(Boolean, default=False)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    passengers: Mapped[int] = mapped_column(Integer, default=1)
    max_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    trip_type: Mapped[str] = mapped_column(String(20), default="round_trip")
    allowed_airlines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocked_airlines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    baggage_included: Mapped[bool] = mapped_column(Boolean, default=False)
    frequency_minutes: Mapped[int] = mapped_column(Integer, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Geographic filters used by a multi-destination ("ANYWHERE") search. Stored
    # as JSON text so the monitor can re-run the same regional sweep later.
    area_scope: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    brazil_regions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    international_regions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidate_destinations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ── Scheduling / control fields (Controle de Buscas) ──────────────────────
    # `status` is the new source of truth ('active'|'paused'|'deleted'|'error'|
    # 'completed'); is_active is kept in sync for backward compatibility with the
    # existing worker (is_active == True ⇔ status == 'active').
    status: Mapped[str] = mapped_column(String(20), default="active", server_default=text("'active'"), index=True)
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    search_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'route' | 'multi'
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("TRUE"))
    consider_miles: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("TRUE"))
    min_mile_value: Mapped[float] = mapped_column(Float, default=0.035, server_default=text("0.035"))


class FlightQuote(Base):
    __tablename__ = "flight_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(Integer, index=True)
    origin: Mapped[str] = mapped_column(String(8), index=True)
    destination: Mapped[str] = mapped_column(String(32), index=True)
    departure_date: Mapped[datetime] = mapped_column(Date)
    return_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    airline: Mapped[str] = mapped_column(String(80))
    price: Mapped[float] = mapped_column(Float, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    stops: Mapped[int] = mapped_column(Integer, default=0)
    booking_link: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    opportunity: Mapped[str] = mapped_column(String(40), default="normal")
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # True only for the latest snapshot of a concrete flight (same origin,
    # destination, dates, airline and provider). Older snapshots are flipped to
    # False on each new save so the "current price" is unambiguous while the full
    # price history is preserved.
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("TRUE"), index=True)


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(Integer, index=True)
    quote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channel: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderLog(Base):
    __tablename__ = "provider_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceLog(Base):
    __tablename__ = "source_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40))
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BestDeal(Base):
    """Snapshot of a best destination opportunity found by the multi-destination
    sweep. Feeds the decision radar and avoids recomputing rankings on every load.
    New table — created automatically by create_all; never replaces flight_quotes.
    """
    __tablename__ = "best_deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    origin_iata: Mapped[str] = mapped_column(String(8), index=True)
    destination_iata: Mapped[str] = mapped_column(String(8), index=True)
    destination_city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    destination_country: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    destination_type: Mapped[str] = mapped_column(String(20), default="national")
    departure_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    return_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    best_cash_price: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_miles: Mapped[int] = mapped_column(Integer, default=0)
    mile_value: Mapped[float] = mapped_column(Float, default=0.0)
    recommendation: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    booking_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserRule(Base):
    """Per-user decision preferences (max price, mile floor, limits). Optional —
    the UI also keeps live prefs in session; this persists them across sessions."""
    __tablename__ = "user_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_email: Mapped[str] = mapped_column(String(255), default="demo@radar.local", index=True)
    max_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_mile_value: Mapped[float] = mapped_column(Float, default=0.035)
    max_stops: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="ambos")
    consider_miles: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchActionLog(Base):
    """Audit trail of control actions on a scheduled search (pause/resume/delete/
    run_now/update_frequency/update_telegram). New table — never replaces existing
    logs; created automatically by create_all."""
    __tablename__ = "search_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(40))
    previous_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SearchRunLog(Base):
    """History of executions of a scheduled search (one row per run). Powers the
    'últimas execuções' panel in Controle de Buscas."""
    __tablename__ = "search_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(Integer, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ok")
    quotes_found: Mapped[int] = mapped_column(Integer, default=0)
    best_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


_ENGINE: Engine | None = None
_SESSION_LOCAL: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _create_engine()
    return _ENGINE


def get_session_local() -> sessionmaker[Session]:
    global _SESSION_LOCAL
    if _SESSION_LOCAL is None:
        _SESSION_LOCAL = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _SESSION_LOCAL


def _create_engine() -> Engine:
    url = normalize_database_url(get_settings().database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {"connect_timeout": 10}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg://") and "sslmode=" not in url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}sslmode=require"
    return url


def database_diagnostics() -> dict[str, str]:
    raw_url = get_settings().database_url
    url = normalize_database_url(raw_url)
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    user = parsed.username or ""
    masked_user = f"{user[:10]}..." if len(user) > 13 else user
    return {
        "driver": parsed.scheme or "-",
        "user": masked_user or "-",
        "host": parsed.hostname or "-",
        "port": str(parsed.port or "-"),
        "database": parsed.path.lstrip("/") or "-",
        "sslmode": query.get("sslmode", "-"),
        "source": "DATABASE_URL" if raw_url != "sqlite:///./radar.db" else "fallback sqlite",
    }


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    ensure_schema()


def _run_migration_ddl(engine: Engine, sql: str, *, retries: int = 6) -> bool:
    """Run one DDL/backfill statement safely against a live database.

    Each statement runs in its OWN short transaction so successful migrations are
    committed incrementally (a later failure never rolls back earlier columns).

    On PostgreSQL we set a short ``lock_timeout`` and a high ``statement_timeout``
    so the statement waits briefly for the AccessExclusiveLock and fails *fast and
    cleanly* if the live app is holding the table — instead of being canceled by
    the global statement timeout. We then retry with backoff to slip in between
    the app's reads. Returns True on success, False if it ultimately gave up
    (non-fatal: the app keeps booting and the next reload retries)."""
    import time

    is_pg = engine.dialect.name == "postgresql"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with engine.begin() as conn:
                if is_pg:
                    # Bounded lock wait + generous statement budget for this txn only.
                    conn.execute(text("SET LOCAL lock_timeout = '6s'"))
                    conn.execute(text("SET LOCAL statement_timeout = '120s'"))
                conn.execute(text(sql))
            return True
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, 4s, 6s, 8s, 10s
    # Give up without crashing startup; surface in logs for diagnosis.
    print(f"[ensure_schema] could not apply (will retry next boot): {sql} -> {last_exc}")
    return False


def ensure_schema() -> None:
    engine = get_engine()
    is_pg = engine.dialect.name == "postgresql"
    existing = inspect(engine)
    table_columns = {table: {column["name"] for column in existing.get_columns(table)} for table in existing.get_table_names()}
    additions = {
        "flight_searches": {
            "adults": "INTEGER DEFAULT 1",
            "updated_at": "TIMESTAMP",
            "area_scope": "VARCHAR(20)",
            "brazil_regions": "TEXT",
            "international_regions": "TEXT",
            "candidate_destinations": "TEXT",
            "status": "VARCHAR(20) DEFAULT 'active'",
            "paused_at": "TIMESTAMP",
            "deleted_at": "TIMESTAMP",
            "last_run_at": "TIMESTAMP",
            "next_run_at": "TIMESTAMP",
            "last_status": "VARCHAR(40)",
            "last_error": "TEXT",
            "search_type": "VARCHAR(20)",
            "telegram_enabled": "BOOLEAN DEFAULT TRUE",
            "consider_miles": "BOOLEAN DEFAULT TRUE",
            "min_mile_value": "FLOAT DEFAULT 0.035",
        },
        "flight_quotes": {
            "raw_payload": "TEXT",
            "collected_at": "TIMESTAMP",
            "is_current": "BOOLEAN DEFAULT TRUE",
        },
        "alert_logs": {
            "sent_at": "TIMESTAMP",
        },
        "provider_logs": {
            "error_message": "TEXT",
        },
    }
    status_just_added = (
        "flight_searches" in table_columns
        and "status" not in table_columns["flight_searches"]
    )
    for table, columns in additions.items():
        if table not in table_columns:
            continue
        missing = [(c, t) for c, t in columns.items() if c not in table_columns[table]]
        if not missing:
            continue
        if is_pg:
            # One ALTER adds every missing column in a single lock acquisition,
            # minimising contention with the live app. IF NOT EXISTS guards races
            # with another instance booting at the same time.
            clauses = ", ".join(f"ADD COLUMN IF NOT EXISTS {c} {t}" for c, t in missing)
            _run_migration_ddl(engine, f"ALTER TABLE {table} {clauses}")
        else:
            # SQLite supports only one ADD COLUMN per ALTER statement.
            for column, column_type in missing:
                _run_migration_ddl(engine, f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    # One-time backfill: derive the new `status` from the legacy is_active flag so
    # existing paused searches don't all become 'active' (only on first add).
    if status_just_added:
        _run_migration_ddl(engine, "UPDATE flight_searches SET status = 'active' WHERE is_active = TRUE", retries=2)
        _run_migration_ddl(engine, "UPDATE flight_searches SET status = 'paused' WHERE is_active = FALSE", retries=2)


@contextmanager
def session_scope() -> Iterator[Session]:
    db = get_session_local()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
