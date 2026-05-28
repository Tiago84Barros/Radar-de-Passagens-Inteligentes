from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts import dispatch_alerts
from app.db import FlightQuote, FlightSearch, ProviderLog, init_db, session_scope
from app.pricing import evaluate_quote
from app.providers import search_all_providers


def _query_from_search(search: FlightSearch) -> dict:
    return {
        "origin": search.origin,
        "destination": search.destination,
        "departure_date": search.departure_date,
        "return_date": search.return_date,
        "passengers": search.passengers,
        "currency": search.currency,
        "max_price": search.max_price,
        "baggage_included": search.baggage_included,
    }


def is_due(search: FlightSearch, now: datetime | None = None) -> bool:
    if not search.is_active:
        return False
    if not search.last_checked_at:
        return True
    now = now or datetime.now(timezone.utc)
    last_checked = search.last_checked_at
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    return now >= last_checked + timedelta(minutes=search.frequency_minutes)


def run_search_once(db, search: FlightSearch) -> int:
    saved = 0
    offers = search_all_providers(_query_from_search(search))
    for offer in offers:
        history = list(
            db.scalars(
                select(FlightQuote)
                .where(
                    FlightQuote.search_id == search.id,
                    FlightQuote.origin == offer.origin,
                    FlightQuote.destination == offer.destination,
                )
                .order_by(FlightQuote.detected_at.desc())
                .limit(50)
            )
        )
        decision = evaluate_quote(search, offer.price, history)
        quote = FlightQuote(
            search_id=search.id,
            origin=offer.origin,
            destination=offer.destination,
            departure_date=offer.departure_date,
            return_date=offer.return_date,
            airline=offer.airline,
            price=offer.price,
            currency=offer.currency,
            duration_minutes=offer.duration_minutes,
            stops=offer.stops,
            booking_link=offer.booking_link,
            provider=offer.provider,
            opportunity=decision.opportunity,
        )
        db.add(quote)
        db.flush()
        saved += 1
        if decision.should_alert:
            dispatch_alerts(db, search, quote, decision)
    search.last_checked_at = datetime.now(timezone.utc)
    db.add(ProviderLog(provider="all", status=f"ok:{saved}"))
    return saved


def run_due_searches(force: bool = False) -> dict:
    init_db()
    with session_scope() as db:
        searches = list(db.scalars(select(FlightSearch).where(FlightSearch.is_active.is_(True))))
        total = 0
        ran = 0
        for search in searches:
            if force or is_due(search):
                total += run_search_once(db, search)
                ran += 1
        return {"searches_checked": ran, "quotes_saved": total}
