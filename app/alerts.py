from __future__ import annotations

from datetime import datetime, timezone

from app.db import MonitoredSearch
from app.formatting import format_brl
from data.airlines_catalog import get_airline_name
from services.miles_service import DEFAULT_CENTS_PER_MILE, estimate_miles_from_cash_price, format_miles
from services.telegram_service import send_telegram_message
from utils.formatters import format_date_br, format_duration_short, format_stops


def build_monitor_alert_message(search: MonitoredSearch, option: dict, recommendation_reason: str | None = None) -> str:
    """Build the Telegram message for a monitored-search hit.

    Includes every field required by spec: origem, destino, data ida/volta,
    companhia, preço, estimativa em milhas, duração total, escalas/conexões,
    fonte/API, motivo da recomendação e link de compra."""
    price = float(option.get("price_brl") or option.get("price") or 0)
    miles = estimate_miles_from_cash_price(price, search.min_mile_value or DEFAULT_CENTS_PER_MILE)
    airline = get_airline_name(option.get("airline") or "")
    duration = format_duration_short(option.get("duration_minutes"))
    stops = format_stops(option.get("stops"))
    source = option.get("provider") or option.get("source") or "—"
    link = option.get("booking_link") or option.get("link") or ""
    reason = recommendation_reason or "Melhor tarifa encontrada dentro da janela monitorada."

    return (
        f"📡 Radar de Passagens Inteligentes — busca rastreada\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✈️  Rota: {search.origin_iata} → {search.destination_iata}\n"
        f"📅  Ida: {format_date_br(option.get('departure_date') or search.departure_date)}\n"
        f"📅  Volta: {format_date_br(option.get('return_date') or search.return_date)}\n"
        f"🏢  Companhia: {airline}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰  Preço: {format_brl(price)}\n"
        f"🏆  Estimativa em milhas: {format_miles(miles)}\n"
        f"   ⚠️ Milhas estimadas — disponibilidade real depende do programa\n"
        f"⏱️  Duração total: {duration or '—'}\n"
        f"🔁  Escalas: {stops or '—'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡  Motivo da recomendação: {reason}\n"
        f"🔌  Fonte: {source}\n"
        f"🔗  Link de compra: {link or '—'}\n"
        f"⏰  Encontrado em: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}"
    )


def dispatch_monitor_alert(search: MonitoredSearch, option: dict, recommendation_reason: str | None = None) -> str:
    """Send the Telegram alert for a monitored-search hit. Returns a status string
    ("sent" / "telegram_not_configured" / "telegram_send_failed" / "skipped")."""
    if not search.telegram_enabled:
        return "skipped"
    message = build_monitor_alert_message(search, option, recommendation_reason)
    ok, detail = send_telegram_message(message)
    return "sent" if ok else detail
