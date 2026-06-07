from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import quote_plus

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


def get_config_value(name: str, default: str | None = None) -> str | None:
    """Read one config value from environment variables or Streamlit secrets."""
    if os.getenv(name):
        return os.getenv(name)
    if st is not None:
        try:
            return st.secrets.get(name, default)
        except Exception:
            return default
    return default


def _first_secret(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = get_config_value(name)
        if value:
            return value
    return default


def _database_url_from_parts() -> str | None:
    user = _first_secret("DB_USER", "POSTGRES_USER", "user")
    password = _first_secret("DB_PASSWORD", "POSTGRES_PASSWORD", "password")
    host = _first_secret("DB_HOST", "POSTGRES_HOST", "host")
    port = _first_secret("DB_PORT", "POSTGRES_PORT", "port", default="5432")
    dbname = _first_secret("DB_NAME", "POSTGRES_DB", "dbname", default="postgres")
    if not all([user, password, host, port, dbname]):
        return None
    return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}"


class Settings:
    database_url: str
    app_password: str | None
    gemini_api_key: str | None
    travelpayouts_token: str | None
    travelpayouts_api_token: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    alert_from_email: str
    github_token: str | None
    github_repo: str | None
    github_workflow: str
    github_ref: str

    def __init__(self) -> None:
        self.database_url = get_config_value("DATABASE_URL") or _database_url_from_parts() or "sqlite:///./radar.db"
        self.app_password = get_config_value("APP_PASSWORD")
        self.gemini_api_key = get_config_value("GEMINI_API_KEY")
        self.travelpayouts_api_token = get_config_value("TRAVELPAYOUTS_API_TOKEN") or get_config_value("TRAVELPAYOUTS_TOKEN")
        self.travelpayouts_token = self.travelpayouts_api_token
        self.telegram_bot_token = get_config_value("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = get_config_value("TELEGRAM_CHAT_ID")
        self.smtp_host = get_config_value("SMTP_HOST")
        self.smtp_port = int(get_config_value("SMTP_PORT", "587") or "587")
        self.smtp_user = get_config_value("SMTP_USER")
        self.smtp_password = get_config_value("SMTP_PASSWORD")
        self.alert_from_email = get_config_value("ALERT_FROM_EMAIL", "alerts@radar.local") or "alerts@radar.local"
        # GitHub Actions trigger: lets the app fire the monitor workflow on demand.
        self.github_token = get_config_value("GITHUB_TOKEN") or get_config_value("GH_TOKEN")
        self.github_repo = get_config_value("GITHUB_REPO")  # e.g. "Tiago84Barros/Radar-de-Passagens-Inteligentes"
        self.github_workflow = get_config_value("GITHUB_WORKFLOW", "monitor-searches.yml") or "monitor-searches.yml"
        self.github_ref = get_config_value("GITHUB_REF", "main") or "main"


def _as_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
