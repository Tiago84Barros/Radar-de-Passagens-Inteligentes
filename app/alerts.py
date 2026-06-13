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

    return_date = option.get("return_date") or search.return_date
    price_block = _build_price_block(option, price, return_date)

    return (
        f"📡 Radar de Passagens Inteligentes — busca rastreada\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✈️  Rota: {search.origin_iata} → {search.destination_iata}\n"
        f"📅  Ida: {format_date_br(option.get('departure_date') or search.departure_date)}\n"
        f"📅  Volta: {format_date_br(return_date)}\n"
        f"🏢  Companhia: {airline}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{price_block}"
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


def _build_price_block(option: dict, price: float, return_date) -> str:
    """Render the price line(s) making it unambiguous whether the value is the
    round-trip total (ida + volta) or a single leg — espelha a mesma lógica do
    card no app. Quando há detalhamento, mostra "Ida X · Volta Y" abaixo."""
    price_note = option.get("price_note") or ""
    is_round_trip = bool(return_date) and price_note != "preco_somente_ida"

    if not is_round_trip:
        # Somente ida — explícito que o valor cobre apenas o trecho de ida.
        suffix = " (estimado só para a ida — conexão via hub)" if price_note == "preco_somente_ida" else ""
        return f"💰  Preço (somente ida): {format_brl(price)}{suffix}\n"

    # Ida e volta: o preço é o valor TOTAL da viagem. Deriva o trecho que faltar
    # a partir do total (total = ida + volta) para sempre mostrar os dois.
    p_ida = option.get("price_outbound")
    p_volta = option.get("price_return")
    if p_ida and not p_volta and price > p_ida:
        p_volta = round(price - p_ida, 2)
    elif p_volta and not p_ida and price > p_volta:
        p_ida = round(price - p_volta, 2)

    block = f"💰  Preço (ida e volta — total): {format_brl(price)}\n"
    if p_ida and p_volta:
        block += f"   ↳ Ida {format_brl(p_ida)} · Volta {format_brl(p_volta)}\n"
    return block


def dispatch_monitor_alert(search: MonitoredSearch, option: dict, recommendation_reason: str | None = None) -> str:
    """Send the Telegram alert for a monitored-search hit. Returns a status string
    ("sent" / "telegram_not_configured" / "telegram_send_failed" / "skipped")."""
    if not search.telegram_enabled:
        return "skipped"
    message = build_monitor_alert_message(search, option, recommendation_reason)
    ok, detail = send_telegram_message(message)
    return "sent" if ok else detail


def build_availability_message(search: MonitoredSearch, available: bool, option: dict | None = None) -> str:
    """Build the Telegram update sent when no *better* fare turned up — it tells
    the user whether the fare we last alerted is still on the market.

    Resolve a dúvida "a passagem deixou de existir ou nunca existiu": a cada
    verificação o bot reconfere a passagem e reporta o status."""
    header = (
        f"📡 Radar de Passagens Inteligentes — atualização do rastreio\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✈️  Rota: {search.origin_iata} → {search.destination_iata}\n"
        f"📅  Ida: {format_date_br(search.departure_date)}\n"
        f"📅  Volta: {format_date_br(search.return_date)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    if available and option:
        price = float(option.get("price_brl") or option.get("price") or 0)
        price_block = _build_price_block(option, price, option.get("return_date") or search.return_date)
        link = option.get("booking_link") or option.get("link") or ""
        return (
            header
            + f"✅  Passagem ainda disponível\n"
            + price_block
            + f"🔗  Link de compra: {link or '—'}\n"
            + f"⏰  Verificado em: {stamp}"
        )

    return (
        header
        + f"❌  Passagem não está mais disponível, aguarde a próxima oportunidade\n"
        + f"⏰  Verificado em: {stamp}"
    )


def dispatch_availability_alert(search: MonitoredSearch, available: bool, option: dict | None = None) -> str:
    """Send the availability-status update via Telegram. Same return contract as
    ``dispatch_monitor_alert``."""
    if not search.telegram_enabled:
        return "skipped"
    message = build_availability_message(search, available, option)
    ok, detail = send_telegram_message(message)
    return "sent" if ok else detail
