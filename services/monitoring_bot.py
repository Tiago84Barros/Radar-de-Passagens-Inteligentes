"""The monitoring bot — runs scheduled checks for tracked searches.

Per spec, the bot does NOT feed the app's main screen with history. It only:
  1. runs each due ``monitored_searches`` row through the search providers
     (Travelpayouts = fonte de precos reais; Gemini = apoio/fallback),
  2. finds the best fare for the tracked window,
  3. sends a Telegram alert when it is worth surfacing,
  4. updates the search's status-summary fields (last_checked_at,
     last_best_price, last_best_link, last_status_message, ...).

No quote history, no price graphs, no separate run-log table — the row IS the
summary. Runs every 4h via ``.github/workflows/monitor-searches.yml`` (cron +
workflow_dispatch) through ``scripts/run_monitoring_bot.py``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts import dispatch_monitor_alert
from app.db import MonitoredSearch, init_db, session_scope
from providers.provider_manager import search_all_providers
from services.decision_engine import REC_BUY, REC_MILES, build_purchase_recommendation
from services.recommendation_service import rank_flight_options

RUNNABLE_STATUS = "active"
DEFAULT_CHECK_FREQUENCY = timedelta(hours=4)
TRACK_WINDOW = timedelta(hours=24)


def is_due(search: MonitoredSearch, now: datetime | None = None) -> bool:
    if (search.status or "").strip().lower() != RUNNABLE_STATUS:
        return False
    if not search.last_checked_at:
        return True
    now = now or datetime.now(timezone.utc)
    last_checked = search.last_checked_at
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    return now >= last_checked + DEFAULT_CHECK_FREQUENCY


def is_within_tracking_window(search: MonitoredSearch, now: datetime | None = None) -> bool:
    """A monitor is active for 24h from creation (spec: "rastrear esta busca 24h")."""
    if not search.created_at:
        return True
    now = now or datetime.now(timezone.utc)
    created = search.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return now <= created + TRACK_WINDOW


def get_monitors_to_run(db, now: datetime | None = None, force: bool = False) -> list[MonitoredSearch]:
    rows = list(db.scalars(select(MonitoredSearch)))
    now = now or datetime.now(timezone.utc)
    return [
        s for s in rows
        if (s.status or "").strip().lower() == RUNNABLE_STATUS
        and is_within_tracking_window(s, now)
        and (force or is_due(s, now))
    ]


def query_from_monitor(search: MonitoredSearch) -> dict:
    return {
        "origin": search.origin_iata,
        "destination": search.destination_iata,
        "departure_date": search.departure_date,
        "return_date": search.return_date,
        "adults": search.adults,
        "passengers": search.adults,
        "currency": "BRL",
        "max_price": search.max_price,
    }


def execute_monitored_search(db, search: MonitoredSearch) -> dict:
    """Run one monitored search, send an alert when worthwhile, and update only
    the status-summary fields on the row. Failure-safe: never raises — records
    the error in ``last_status_message`` instead."""
    try:
        offers = search_all_providers(query_from_monitor(search))
    except Exception as exc:  # noqa: BLE001
        search.last_checked_at = datetime.now(timezone.utc)
        search.updated_at = search.last_checked_at
        search.last_status_message = f"Erro na busca: {exc}"[:500]
        return {"ok": False, "message": search.last_status_message}

    options = [_offer_to_option(o, search) for o in offers]
    ranking = rank_flight_options(options, _preferences(search))
    best = ranking.get("recommended_option") or ranking.get("cheapest_option")

    notified = False
    status_message = "Nenhuma tarifa encontrada nesta verificação."
    if best:
        rec = _recommendation_for(best, search)
        status_message = (
            f"Melhor tarifa: R$ {best['price_brl']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            + f" — {rec['recommendation']}"
        )
        worth_alert = bool(
            (search.max_price and best["price_brl"] <= search.max_price)
            or rec["recommendation"] in {REC_BUY, REC_MILES}
        )
        already_notified_recently = bool(
            search.last_notification_at
            and search.last_best_price
            and best["price_brl"] >= search.last_best_price
        )
        if worth_alert and not already_notified_recently:
            status = dispatch_monitor_alert(search, best, rec.get("main_reason"))
            notified = status == "sent"

    search.last_checked_at = datetime.now(timezone.utc)
    search.updated_at = search.last_checked_at
    if best:
        if search.last_best_price is None or best["price_brl"] < search.last_best_price:
            search.last_best_price = best["price_brl"]
            search.last_best_link = best.get("booking_link")
    search.last_status_message = status_message[:500]
    if notified:
        search.last_notification_at = datetime.now(timezone.utc)

    return {"ok": True, "message": status_message, "notified": notified}


def run_due_monitors(force: bool = False) -> dict:
    init_db()
    with session_scope() as db:
        searches = get_monitors_to_run(db, force=force)
        checked = 0
        notified = 0
        for search in searches:
            result = execute_monitored_search(db, search)
            checked += 1
            if result.get("notified"):
                notified += 1
        return {"monitors_checked": checked, "alerts_sent": notified}


def _preferences(search: MonitoredSearch) -> dict:
    return {
        "max_price": search.max_price,
        "max_stops": search.max_stops,
        "max_duration_minutes": search.max_duration_minutes,
        "min_mile_value": search.min_mile_value,
    }


def _recommendation_for(option: dict, search: MonitoredSearch) -> dict:
    return build_purchase_recommendation(
        [option],
        {
            "max_price": search.max_price,
            "consider_miles": search.consider_miles,
            "user_min_mile_value": search.min_mile_value,
            "departure_date": search.departure_date,
        },
    )


def _offer_to_option(offer: dict, search: MonitoredSearch) -> dict:
    from services.miles_service import enrich_deal_with_miles

    deal = {
        "price_brl": float(offer.get("price") or 0),
        "airline": offer.get("airline") or "",
        "provider": offer.get("provider") or offer.get("source") or "",
        "stops": offer.get("stops"),
        "duration_minutes": offer.get("duration_minutes"),
        "departure_date": offer.get("departure_date") or search.departure_date,
        "return_date": offer.get("return_date") or search.return_date,
        "booking_link": offer.get("booking_link") or "",
        "origin_iata": offer.get("origin") or search.origin_iata,
        "destination_iata": offer.get("destination") or search.destination_iata,
        "score": int(offer.get("score") or 0),
    }
    return enrich_deal_with_miles(deal, search.min_mile_value or 0.035)
