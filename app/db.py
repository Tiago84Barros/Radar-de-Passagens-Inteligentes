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


class MonitoredSearch(Base):
    """A search the user opted to track for 24h. Stores ONLY the search config and
    a status summary — never a price/result history (spec: sem banco historico).

    The bot re-runs this search on a schedule, updates the summary fields below,
    and sends a Telegram alert when it finds the best fare. The manual search
    screen never reads from this table — it is session-only."""

    __tablename__ = "monitored_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default=text("'active'"), index=True)

    origin_iata: Mapped[str] = mapped_column(String(8), index=True)
    origin_city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    destination_iata: Mapped[str] = mapped_column(String(8), index=True)
    destination_city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    departure_date: Mapped[datetime] = mapped_column(Date)
    return_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    trip_type: Mapped[str] = mapped_column(String(20), default="round_trip")

    max_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    consider_miles: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("TRUE"))
    min_mile_value: Mapped[float] = mapped_column(Float, default=0.035, server_default=text("0.035"))
    max_stops: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    search_window_days: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("TRUE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notification_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_best_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_best_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_status_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
    """Hook for additive column migrations on ``monitored_searches``.

    Currently a no-op: the model maps only columns created by ``create_all`` —
    no extra ALTERs are needed. IMPORTANT: never map a column here that an
    additive ``ALTER TABLE`` might fail to apply on the live DB — if the model
    requires a column the database lacks, every ORM query raises and the whole
    monitor run goes silent. State that used to need a new column is derived from
    existing columns (see ``last_status_message`` usage in monitoring_bot)."""
    return None


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
