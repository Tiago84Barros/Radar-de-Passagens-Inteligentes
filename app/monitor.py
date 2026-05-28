from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts import dispatch_alerts
from app.deals import calculate_deal_score
from app.db import FlightQuote, FlightSearch, ProviderLog, init_db, session_scope
from providers.provider_manager import get_last_provider_diagnostic, search_all_providers


def _query_from_search(search: FlightSearch) -> dict:
    return {
        "origin": search.origin,
        "destination": search.destination,
        "departure_date": search.departure_date,
        "return_date": search.return_date,
        "adults": search.adults or search.passengers,
        "passengers": search.adults or search.passengers,
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
    provider_diagnostic = get_last_provider_diagnostic()
    for offer in offers:
        history = list(
            db.scalars(
                select(FlightQuote)
                .where(
                    FlightQuote.search_id == search.id,
                    FlightQuote.origin == offer["origin"],
                    FlightQuote.destination == offer["destination"],
                )
                .order_by(FlightQuote.detected_at.desc())
                .limit(50)
            )
        )
        decision = calculate_deal_score(offer, search.max_price, history)
        quote = FlightQuote(
            search_id=search.id,
            origin=offer["origin"],
            destination=offer["destination"],
            departure_date=_parse_date(offer["departure_date"]),
            return_date=_parse_date(offer.get("return_date")),
            airline=offer.get("airline") or "",
            price=offer["price"],
            currency=offer.get("currency") or search.currency,
            duration_minutes=offer.get("duration_minutes") or 0,
            stops=offer.get("stops") or 0,
            booking_link=offer.get("booking_link") or "",
            provider=offer["provider"],
            opportunity=decision["classification"],
            raw_payload=json.dumps(offer.get("raw_payload", {}), ensure_ascii=False),
            collected_at=datetime.now(timezone.utc),
        )
        db.add(quote)
        db.flush()
        saved += 1
        if decision["is_opportunity"]:
            dispatch_alerts(db, search, quote, decision)
    search.last_checked_at = datetime.now(timezone.utc)
    db.add(
        ProviderLog(
            provider=provider_diagnostic.get("provider", "travelpayouts"),
            status=str(provider_diagnostic.get("status", "unknown"))[:40],
            error_message=provider_diagnostic.get("message"),
        )
    )
    db.add(ProviderLog(provider="all", status=f"ok:{saved}"))
    return saved


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


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
