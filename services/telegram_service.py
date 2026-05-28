from __future__ import annotations

import requests

from app.settings import get_settings


def send_telegram_message(message: str) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False, "telegram_not_configured"
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": message},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return False, "telegram_send_failed"
    return True, "sent"
