from __future__ import annotations

import os
from functools import lru_cache

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


def _secret(name: str, default: str | None = None) -> str | None:
    if os.getenv(name):
        return os.getenv(name)
    if st is not None:
        try:
            return st.secrets.get(name, default)
        except Exception:
            return default
    return default


class Settings:
    database_url: str
    app_password: str | None
    amadeus_client_id: str | None
    amadeus_client_secret: str | None
    kiwi_api_key: str | None
    travelpayouts_token: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    alert_from_email: str

    def __init__(self) -> None:
        self.database_url = _secret("DATABASE_URL", "sqlite:///./radar.db") or "sqlite:///./radar.db"
        self.app_password = _secret("APP_PASSWORD")
        self.amadeus_client_id = _secret("AMADEUS_CLIENT_ID")
        self.amadeus_client_secret = _secret("AMADEUS_CLIENT_SECRET")
        self.kiwi_api_key = _secret("KIWI_API_KEY")
        self.travelpayouts_token = _secret("TRAVELPAYOUTS_TOKEN")
        self.telegram_bot_token = _secret("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = _secret("TELEGRAM_CHAT_ID")
        self.smtp_host = _secret("SMTP_HOST")
        self.smtp_port = int(_secret("SMTP_PORT", "587") or "587")
        self.smtp_user = _secret("SMTP_USER")
        self.smtp_password = _secret("SMTP_PASSWORD")
        self.alert_from_email = _secret("ALERT_FROM_EMAIL", "alerts@radar.local") or "alerts@radar.local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
