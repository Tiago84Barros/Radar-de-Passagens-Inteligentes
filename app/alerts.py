from __future__ import annotations

import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone

import httpx

from app.formatting import format_brl
from app.db import AlertLog, FlightQuote, FlightSearch
from app.settings import get_settings
from services.telegram_service import send_telegram_message


def build_alert_message(search: FlightSearch, quote: FlightQuote, decision) -> str:
    comparison = search.max_price - quote.price
    reasons = getattr(decision, "reasons", None) or decision.get("reasons", [decision.get("classification", quote.opportunity)])
    return (
        "Radar de Passagens Inteligentes\n"
        f"Rota: {quote.origin} -> {quote.destination}\n"
        f"Datas: {quote.departure_date}{' até ' + str(quote.return_date) if quote.return_date else ''}\n"
        f"Preço encontrado: {format_brl(quote.price)}\n"
        f"Companhia: {quote.airline}\n"
        f"Economia estimada: {format_brl(comparison if comparison > 0 else 0)}\n"
        f"Classificação: {quote.opportunity}\n"
        f"Provedor: {quote.provider}\n"
        f"Link: {quote.booking_link}\n"
        f"Motivos: {'; '.join(reasons)}"
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
    email["Subject"] = "Alerta de passagem barata"
    email.set_content(message)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(email)
    return "sent"


def dispatch_alerts(db, search: FlightSearch, quote: FlightQuote, decision: PriceDecision) -> None:
    message = build_alert_message(search, quote, decision)
    for channel in ("telegram", "email"):
        try:
            status = send_telegram(message) if channel == "telegram" else send_email(search.owner_email, message)
        except Exception as exc:  # noqa: BLE001
            status = f"failed: {exc}"
        db.add(AlertLog(search_id=search.id, quote_id=quote.id, channel=channel, message=message, status=status, sent_at=datetime.now(timezone.utc)))
