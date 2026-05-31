from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from app.db import AlertLog, FlightQuote, FlightSearch
from app.formatting import format_brl
from app.settings import get_settings
from services.miles_service import DEFAULT_CENTS_PER_MILE, estimate_miles, format_miles
from services.telegram_service import send_telegram_message


def build_alert_message(search: FlightSearch, quote: FlightQuote, decision) -> str:
    comparison = search.max_price - quote.price
    reasons = getattr(decision, "reasons", None) or decision.get("reasons", [decision.get("classification", quote.opportunity)])
    score = getattr(decision, "score", None) or decision.get("score", "-")
    drop = getattr(decision, "drop_vs_average", None) or decision.get("drop_vs_average", 0)
    classification = getattr(decision, "classification", None) or decision.get("classification", quote.opportunity or "-")

    miles = estimate_miles(quote.price, DEFAULT_CENTS_PER_MILE)
    miles_label = format_miles(miles)

    # Decision-based fields (spec §7): recommendation, main reason and implied
    # mile value. These come from the decision engine via monitoring_service.
    recommendation = getattr(decision, "recommendation", None) or decision.get("recommendation")
    rec_reason = getattr(decision, "recommendation_reason", None) or decision.get("recommendation_reason")
    mile_value = getattr(decision, "mile_value", None) or decision.get("mile_value") or 0.0
    mile_value_label = f"R$ {float(mile_value):.3f}".replace(".", ",") if mile_value else "—"

    # Emoji for classification
    emoji_map = {
        "excelente oportunidade": "🏆",
        "Excelente oportunidade": "🏆",
        "otima oportunidade": "⭐",
        "ótima oportunidade": "⭐",
        "Ótima oportunidade": "⭐",
        "boa oportunidade": "✅",
        "Boa oportunidade": "✅",
    }
    cls_lower = (classification or "").lower().strip()
    emoji = next((v for k, v in emoji_map.items() if k.lower() in cls_lower), "ℹ️")

    dep_date = ""
    if quote.departure_date:
        try:
            if hasattr(quote.departure_date, "strftime"):
                dep_date = quote.departure_date.strftime("%d/%m/%Y")
            else:
                from datetime import date
                d = date.fromisoformat(str(quote.departure_date))
                dep_date = d.strftime("%d/%m/%Y")
        except Exception:
            dep_date = str(quote.departure_date)

    ret_date = ""
    if quote.return_date:
        try:
            if hasattr(quote.return_date, "strftime"):
                ret_date = quote.return_date.strftime("%d/%m/%Y")
            else:
                from datetime import date
                d = date.fromisoformat(str(quote.return_date))
                ret_date = d.strftime("%d/%m/%Y")
        except Exception:
            ret_date = str(quote.return_date)

    date_info = dep_date
    if ret_date:
        date_info += f" a {ret_date}"

    rec_line = f"🧭  Recomendação: {recommendation}\n" if recommendation else ""
    rec_reason_line = f"💡  Motivo: {rec_reason}\n" if rec_reason else ""

    return (
        f"{emoji} Radar de Passagens Inteligentes\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✈️  Rota: {quote.origin} → {quote.destination}\n"
        f"📅  Datas: {date_info or 'a confirmar'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{rec_line}"
        f"{rec_reason_line}"
        f"💰  Preço encontrado: {format_brl(quote.price)}\n"
        f"🏆  Milhas estimadas: {miles_label}\n"
        f"🪙  Valor implícito da milha: {mile_value_label}\n"
        f"    ⚠️ Milhas estimadas — não representa disponibilidade real\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️  Classificação: {classification}\n"
        f"📊  Score: {score}/100\n"
        f"📉  Queda vs média histórica: {float(drop or 0):.1f}%\n"
        f"✈️  Companhia: {quote.airline}\n"
        f"💸  Economia estimada: {format_brl(comparison if comparison > 0 else 0)}\n"
        f"🔌  Fonte: {quote.provider}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗  Link: {quote.booking_link}\n"
        f"⏰  Detectado em: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}\n"
        f"📝  Motivos: {'; '.join(reasons)}"
    )


def send_telegram(message: str) -> str:
    ok, detail = send_telegram_message(message)
    return "sent" if ok else detail


def send_email(to_email: str, message: str) -> str:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_user:
        return "mock"
    email = EmailMessage()
    email["From"] = settings.alert_from_email
    email["To"] = to_email
    email["Subject"] = "✈️ Alerta de passagem barata — Radar Inteligente"
    email.set_content(message)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(email)
    return "sent"


def dispatch_alerts(db, search: FlightSearch, quote: FlightQuote, decision) -> None:
    message = build_alert_message(search, quote, decision)
    for channel in ("telegram", "email"):
        try:
            status = send_telegram(message) if channel == "telegram" else send_email(search.owner_email, message)
        except Exception as exc:  # noqa: BLE001
            status = f"failed: {exc}"
        db.add(
            AlertLog(
                search_id=search.id,
                quote_id=quote.id,
                channel=channel,
                message=message,
                status=status,
                sent_at=datetime.now(timezone.utc),
            )
        )
