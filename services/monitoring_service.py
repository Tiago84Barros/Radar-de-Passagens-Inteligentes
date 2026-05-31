from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts import dispatch_alerts
from app.db import FlightSearch, init_db, session_scope
from providers.provider_manager import get_last_provider_diagnostic, search_all_providers, search_year_price_calendar
from services.database_service import has_recent_alert, log_source, quote_history, save_quote
from services.deal_score import calculate_deal_score, should_send_alert
from services.decision_engine import REC_BUY, REC_MILES, build_purchase_recommendation


def query_from_search(search: FlightSearch) -> dict:
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


def run_search_once(db, search: FlightSearch, include_year_calendar: bool = False) -> int:
    saved = 0
    offers = search_all_providers(query_from_search(search))
    provider_diagnostic = get_last_provider_diagnostic()
    for offer in offers:
        history = quote_history(db, search, offer)
        decision = calculate_deal_score(offer, search.max_price, history)
        # Enrich the decision with a decision-engine recommendation so alerts are
        # decision-based, not just price-based (spec §7). Never break collection.
        decision = _enrich_decision(decision, offer, search, history)
        quote = save_quote(db, search, offer, decision["classification"])
        saved += 1
        alert_worthy = should_send_alert(decision, offer, search.max_price) or decision.get(
            "recommendation"
        ) in {REC_BUY, REC_MILES}
        if alert_worthy and not has_recent_alert(db, search, quote):
            dispatch_alerts(db, search, quote, decision)
    if include_year_calendar:
        calendar_offers = search_year_price_calendar(query_from_search(search))
        for offer in calendar_offers:
            history = quote_history(db, search, offer)
            decision = calculate_deal_score(offer, search.max_price, history)
            save_quote(db, search, offer, decision["classification"])
            saved += 1
        if calendar_offers:
            log_source(db, "travelpayouts_calendar", "ok", f"{len(calendar_offers)} cotacao(oes) anuais salvas")
    search.last_checked_at = datetime.now(timezone.utc)
    log_source(
        db,
        str(provider_diagnostic.get("provider", "hybrid")),
        str(provider_diagnostic.get("status", "unknown")),
        provider_diagnostic.get("message"),
    )
    for scraper_log in provider_diagnostic.get("scrapers", []) or []:
        log_source(db, scraper_log.get("source", "scraper"), scraper_log.get("status", "unknown"), scraper_log.get("message"))
    log_source(db, "all", f"ok:{saved}", f"{saved} cotacao(oes) salvas")
    return saved


def _enrich_decision(decision: dict, offer: dict, search: FlightSearch, history: list) -> dict:
    """Attach a decision-engine recommendation + implied mile value to the score
    decision so alerts can be phrased in decision terms. Failure-safe: returns the
    original decision untouched on any error (the monitor must never break)."""
    try:
        deal = {
            "price_brl": float(offer.get("price") or 0),
            "airline": offer.get("airline") or "",
            "provider": offer.get("provider") or offer.get("source") or "",
            "score": int(decision.get("score") or 0),
            "stops": offer.get("stops"),
            "duration_minutes": offer.get("duration_minutes"),
            "departure_date": offer.get("departure_date"),
            "return_date": offer.get("return_date"),
            "booking_link": offer.get("booking_link") or "",
            "origin_iata": offer.get("origin") or search.origin,
            "destination_iata": offer.get("destination") or search.destination,
        }
        prices = [float(getattr(h, "price", 0) or 0) for h in history or []]
        prices = [p for p in prices if p > 0]
        recent = {}
        if prices:
            recent = {"recent_min": min(prices), "recent_avg": sum(prices) / len(prices), "sample_size": len(prices)}
        rec = build_purchase_recommendation(
            [deal],
            {"max_price": search.max_price, "consider_miles": True, "departure_date": offer.get("departure_date")},
            recent_history=recent,
        )
        decision = dict(decision)
        decision["recommendation"] = rec["recommendation"]
        decision["recommendation_reason"] = rec["main_reason"]
        decision["confidence"] = rec["confidence"]
        decision["mile_value"] = (rec.get("cash_vs_miles") or {}).get("mile_value", 0.0)
    except Exception:
        return decision
    return decision


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
