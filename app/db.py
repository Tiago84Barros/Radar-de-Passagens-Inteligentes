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


def ensure_schema() -> None:
    engine = get_engine()
    existing = inspect(engine)
    table_columns = {table: {column["name"] for column in existing.get_columns(table)} for table in existing.get_table_names()}
    additions = {
        "flight_searches": {
            "adults": "INTEGER DEFAULT 1",
            "updated_at": "TIMESTAMP",
        },
        "flight_quotes": {
            "raw_payload": "TEXT",
            "collected_at": "TIMESTAMP",
        },
        "alert_logs": {
            "sent_at": "TIMESTAMP",
        },
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in table_columns:
                continue
            for column, column_type in columns.items():
                if column not in table_columns[table]:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))


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
