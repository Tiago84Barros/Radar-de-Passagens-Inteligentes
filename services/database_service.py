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


def has_recent_alert(db, search: FlightSearch, quote: FlightQuote, within_hours: int = 12) -> bool:
    """True when a sent alert already exists recently for an equal-or-better price
    on this search — used to avoid duplicate Telegram alerts (spec §7).

    We look at AlertLog rows joined to their quote for the same search within the
    window; if any alerted price is <= the new price, the new one adds no news."""
    from datetime import datetime, timedelta, timezone

    from app.db import AlertLog

    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    recent = db.scalars(
        select(AlertLog)
        .where(
            AlertLog.search_id == search.id,
            AlertLog.channel == "telegram",
            AlertLog.status == "sent",
        )
        .order_by(AlertLog.created_at.desc())
        .limit(20)
    )
    new_price = float(getattr(quote, "price", 0) or 0)
    for log in recent:
        created = log.created_at
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                continue
        prior = db.get(FlightQuote, log.quote_id) if log.quote_id else None
        if prior is None:
            # An alert was sent recently but we can't compare prices → be safe,
            # treat as duplicate only when same route.
            if prior is None and new_price > 0:
                return True
            continue
        if (
            prior.origin == quote.origin
            and prior.destination == quote.destination
            and float(prior.price or 0) <= new_price
        ):
            return True
    return False


def save_best_deals(db, origin_iata: str, opportunities: list[dict]) -> int:
    """Persist multi-destination opportunities into the best_deals table.

    Keeps the latest snapshot per (origin, destination): older rows for the same
    pair are removed so the table stays a compact 'current best' view (the full
    quote history still lives in flight_quotes). Failure-safe and idempotent."""
    from datetime import datetime, timezone

    from app.db import BestDeal

    saved = 0
    for opp in opportunities or []:
        dest = str(opp.get("destination_iata") or "").upper()
        if not dest:
            continue
        db.query(BestDeal).filter(
            BestDeal.origin_iata == origin_iata, BestDeal.destination_iata == dest
        ).delete()
        db.add(
            BestDeal(
                origin_iata=origin_iata,
                destination_iata=dest,
                destination_city=opp.get("destination_city"),
                destination_country=opp.get("destination_country"),
                destination_type=opp.get("destination_type") or "national",
                departure_date=_parse_date(opp.get("departure_date")),
                return_date=_parse_date(opp.get("return_date")),
                best_cash_price=float(opp.get("cash_price") or 0),
                estimated_miles=int(opp.get("estimated_miles") or 0),
                mile_value=float(opp.get("mile_value") or 0),
                recommendation=opp.get("recommendation"),
                score=int(opp.get("score") or 0),
                source=str(opp.get("source") or "")[:60],
                booking_link=opp.get("booking_link"),
                found_at=datetime.now(timezone.utc),
            )
        )
        saved += 1
    return saved


def log_source(db, source: str, status: str, message: str | None = None) -> None:
    db.add(SourceLog(source=source[:40], status=status[:40], message=message))
    db.add(ProviderLog(provider=source[:40], status=status[:40], error_message=message))


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()
