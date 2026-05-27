from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx

from app.db import AlertLog, FlightQuote, FlightSearch
from app.pricing import PriceDecision
from app.settings import get_settings


def build_alert_message(search: FlightSearch, quote: FlightQuote, decision: PriceDecision) -> str:
    comparison = search.max_price - quote.price
    return (
        "Radar de Passagens Inteligentes\n"
        f"Rota: {quote.origin} -> {quote.destination}\n"
        f"Datas: {quote.departure_date}{' até ' + str(quote.return_date) if quote.return_date else ''}\n"
        f"Preço encontrado: {quote.currency} {quote.price:,.2f}\n"
        f"Companhia: {quote.airline}\n"
        f"Comparação com limite: {quote.currency} {comparison:,.2f}\n"
        f"Classificação: {quote.opportunity}\n"
        f"Provedor: {quote.provider}\n"
        f"Link: {quote.booking_link}\n"
        f"Motivos: {'; '.join(decision.reasons)}"
    )


def send_telegram(message: str) -> str:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return "mock"
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    response = httpx.post(url, json={"chat_id": settings.telegram_chat_id, "text": message}, timeout=15)
    response.raise_for_status()
    return "sent"


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
        db.add(AlertLog(search_id=search.id, quote_id=quote.id, channel=channel, message=message, status=status))
