from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, update

from app.db import FlightQuote, FlightSearch, ProviderLog, SourceLog


def quote_history(db, search: FlightSearch, offer: dict[str, Any], limit: int = 50) -> list[FlightQuote]:
    return list(
        db.scalars(
            select(FlightQuote)
            .where(
                FlightQuote.search_id == search.id,
                FlightQuote.origin == offer["origin"],
                FlightQuote.destination == offer["destination"],
            )
            .order_by(FlightQuote.detected_at.desc())
            .limit(limit)
        )
    )


def save_quote(db, search: FlightSearch, offer: dict[str, Any], opportunity: str) -> FlightQuote:
    origin = offer["origin"]
    destination = offer["destination"]
    departure_date = _parse_date(offer["departure_date"])
    return_date = _parse_date(offer.get("return_date"))
    airline = offer.get("airline") or ""
    provider = offer.get("provider") or offer.get("source") or "unknown"

    # Airfares expire and re-price: a new snapshot of the same concrete flight
    # (same route, dates, airline and provider) supersedes the previous one.
    # Flip older snapshots to is_current=False so exactly one row stays "current"
    # while the full price history is preserved for the History tab.
    db.execute(
        update(FlightQuote)
        .where(
            FlightQuote.origin == origin,
            FlightQuote.destination == destination,
            FlightQuote.departure_date == departure_date,
            FlightQuote.return_date == return_date,
            FlightQuote.airline == airline,
            FlightQuote.provider == provider,
            FlightQuote.is_current.is_(True),
        )
        .values(is_current=False)
    )

    quote = FlightQuote(
        search_id=search.id,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        airline=airline,
        price=offer["price"],
        currency=offer.get("currency") or search.currency,
        duration_minutes=int(offer.get("duration_minutes") or 0),
        stops=int(offer.get("stops") or 0),
        booking_link=offer.get("booking_link") or "",
        provider=provider,
        opportunity=opportunity,
        raw_payload=json.dumps(offer.get("raw_payload", {}), ensure_ascii=False),
        collected_at=datetime.now(timezone.utc),
        is_current=True,
    )
    db.add(quote)
    db.flush()
    return quote


def log_source(db, source: str, status: str, message: str | None = None) -> None:
    db.add(SourceLog(source=source[:40], status=status[:40], message=message))
    db.add(ProviderLog(provider=source[:40], status=status[:40], error_message=message))


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()
