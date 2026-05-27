from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, create_engine, func
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
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(Integer, index=True)
    quote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channel: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderLog(Base):
    __tablename__ = "provider_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _engine():
    url = get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
