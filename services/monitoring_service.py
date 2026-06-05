from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts import dispatch_alerts
from app.db import FlightSearch, SearchRunLog, init_db, session_scope
from providers.provider_manager import get_last_provider_diagnostic, search_all_providers, search_year_price_calendar
from services.database_service import has_recent_alert, log_source, prune_old_quotes, quote_history, save_quote
from services.deal_score import calculate_deal_score, should_send_alert
from services.decision_engine import REC_BUY, REC_MILES, build_purchase_recommendation

# Only searches in this status are executed by the worker (spec §6).
RUNNABLE_STATUS = "active"


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


def effective_status(search: FlightSearch) -> str:
    """The search status, falling back to the legacy is_active flag when the new
    `status` column is empty (backward compatibility)."""
    status = (getattr(search, "status", None) or "").strip().lower()
    if status:
        return status
    return "active" if search.is_active else "paused"


def is_expired(search: FlightSearch, today: date | None = None) -> bool:
    """A specific-route search whose departure date has passed is expired. Multi
    destination ("ANYWHERE") sweeps use a forward window and never expire here."""
    if str(search.destination or "").upper() == "ANYWHERE":
        return False
    dep = search.departure_date
    if dep is None:
        return False
    if isinstance(dep, datetime):
        dep = dep.date()
    return dep < (today or date.today())


def is_due(search: FlightSearch, now: datetime | None = None) -> bool:
    # Gate on the status column (the panel's source of truth), not the legacy
    # is_active flag — a "Buscar agora" search can have status='active' but
    # is_active=False (default mismatch), and the panel still shows it as Ativa.
    if effective_status(search) != RUNNABLE_STATUS:
        return False
    if not search.last_checked_at:
        return True
    now = now or datetime.now(timezone.utc)
    last_checked = search.last_checked_at
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    return now >= last_checked + timedelta(minutes=search.frequency_minutes)


def is_eligible(search: FlightSearch, now: datetime | None = None, force: bool = False) -> bool:
    """Whether the worker should run this search now: effective status 'active',
    not expired, and due (unless forced).

    Uses ``effective_status`` (the status column) rather than the legacy
    ``is_active`` flag so the worker stays consistent with the Controle de Buscas
    panel. The two can disagree: a search created via "Buscar agora" gets
    is_active=False but status defaults to 'active'; the panel shows it as Ativa,
    so the worker must honour it too."""
    if effective_status(search) != RUNNABLE_STATUS:
        return False
    if is_expired(search):
        return False
    return force or is_due(search, now)


def get_searches_to_run(db, now: datetime | None = None, force: bool = False) -> list[FlightSearch]:
    """Return the searches the worker should execute now (spec §6).

    Ignores paused/deleted/completed/error statuses, expired searches, and those
    not yet due. ``force`` skips the frequency check. This is the single source of
    truth the GitHub Actions worker uses to decide what runs.

    Loads every search and filters by ``is_eligible`` (which gates on the status
    column) instead of a ``WHERE is_active = True`` SQL filter — otherwise searches
    with status='active' but the legacy is_active=False (the "Buscar agora" case)
    would be silently skipped even though the panel shows them as Ativa."""
    rows = list(db.scalars(select(FlightSearch)))
    return [s for s in rows if is_eligible(s, now=now, force=force)]


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
        # Per-search Telegram switch (spec §15): when off, still collect/save the
        # quote but don't dispatch an alert.
        telegram_on = bool(getattr(search, "telegram_enabled", True))
        if alert_worthy and telegram_on and not has_recent_alert(db, search, quote):
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


def _best_price_for_search(db, search: FlightSearch) -> float | None:
    from app.db import FlightQuote
    from sqlalchemy import func as _func

    val = db.scalar(
        select(_func.min(FlightQuote.price)).where(
            FlightQuote.search_id == search.id, FlightQuote.price > 0
        )
    )
    return float(val) if val else None


def execute_search(db, search: FlightSearch, include_year_calendar: bool = False, source: str = "worker") -> int:
    """Run one search and record control/run-log fields (spec §5/§13).

    Updates last_run_at / last_status / last_error / next_run_at on the search and
    appends a SearchRunLog row. Returns the number of quotes saved. Failure-safe:
    a single failing search records an 'error' run and is re-raised by the caller
    only via the return value (never crashes the worker loop)."""
    started = datetime.now(timezone.utc)
    try:
        saved = run_search_once(db, search, include_year_calendar=include_year_calendar)
        best = _best_price_for_search(db, search)
        search.last_run_at = started
        search.last_status = "ok"
        search.last_error = None
        search.next_run_at = started + timedelta(minutes=search.frequency_minutes or 60)
        search.updated_at = datetime.now(timezone.utc)
        db.add(
            SearchRunLog(
                search_id=search.id, started_at=started, finished_at=datetime.now(timezone.utc),
                status="ok", quotes_found=saved, best_price=best, source=source,
            )
        )
        return saved
    except Exception as exc:  # noqa: BLE001
        search.last_run_at = started
        search.last_status = "error"
        search.last_error = str(exc)[:500]
        search.next_run_at = started + timedelta(minutes=search.frequency_minutes or 60)
        db.add(
            SearchRunLog(
                search_id=search.id, started_at=started, finished_at=datetime.now(timezone.utc),
                status="error", quotes_found=0, error_message=str(exc)[:500], source=source,
            )
        )
        return 0


def run_due_searches(force: bool = False, retention_days: int = 90) -> dict:
    init_db()
    with session_scope() as db:
        searches = get_searches_to_run(db, force=force)
        total = 0
        ran = 0
        for search in searches:
            total += execute_search(db, search, source="worker")
            ran += 1
        # Housekeeping: trim superseded snapshots older than the retention window
        # so the database doesn't grow unbounded. Failure-safe — never breaks a run.
        pruned = {}
        try:
            pruned = prune_old_quotes(db, keep_days=retention_days)
        except Exception:
            pruned = {}
        return {"searches_checked": ran, "quotes_saved": total, "pruned": pruned}
