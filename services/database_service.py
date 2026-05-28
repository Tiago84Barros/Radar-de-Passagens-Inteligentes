from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

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
    quote = FlightQuote(
        search_id=search.id,
        origin=offer["origin"],
        destination=offer["destination"],
        departure_date=_parse_date(offer["departure_date"]),
        return_date=_parse_date(offer.get("return_date")),
        airline=offer.get("airline") or "",
        price=offer["price"],
        currency=offer.get("currency") or search.currency,
        duration_minutes=int(offer.get("duration_minutes") or 0),
        stops=int(offer.get("stops") or 0),
        booking_link=offer.get("booking_link") or "",
        provider=offer.get("provider") or offer.get("source") or "unknown",
        opportunity=opportunity,
        raw_payload=json.dumps(offer.get("raw_payload", {}), ensure_ascii=False),
        collected_at=datetime.now(timezone.utc),
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
