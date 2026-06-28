"""Sanitized SerpApi quota information for the settings screen."""
from __future__ import annotations

from typing import Any

import requests

from app.settings import Settings, get_settings

SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"
REQUEST_TIMEOUT_SECONDS = 10


def fetch_serpapi_usage(settings: Settings | None = None) -> dict[str, Any]:
    """Return quota fields without exposing account identity or API credentials."""
    settings = settings or get_settings()
    api_key = getattr(settings, "serpapi_api_key", None)
    if not api_key:
        return {
            "ok": False,
            "status": "not_configured",
            "message": "SERPAPI_API_KEY não configurada.",
        }

    try:
        response = requests.get(
            SERPAPI_ACCOUNT_URL,
            params={"api_key": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return _error("Não foi possível consultar o limite da SerpApi agora.")

    if response.status_code in {401, 403}:
        return _error("A SerpApi recusou a chave configurada.", status="invalid_key")
    if response.status_code >= 400:
        return _error(
            f"A SerpApi não retornou o limite da conta (HTTP {response.status_code})."
        )

    try:
        payload = response.json()
    except (TypeError, ValueError):
        return _error("A SerpApi retornou uma resposta de limite inválida.")
    if not isinstance(payload, dict) or payload.get("error"):
        return _error("A SerpApi não retornou os dados de limite da conta.")

    monthly_limit = _as_int(payload.get("searches_per_month"))
    monthly_usage = _as_int(payload.get("this_month_usage"))
    plan_left = _as_int(payload.get("plan_searches_left"))
    total_left = _as_int(payload.get("total_searches_left"))
    extra_credits = _as_int(payload.get("extra_credits"))
    last_hour = _as_int(payload.get("last_hour_searches"))
    hourly_limit = _as_int(payload.get("account_rate_limit_per_hour"))

    if total_left is None:
        total_left = plan_left
    if monthly_usage is None and monthly_limit is not None and plan_left is not None:
        monthly_usage = max(monthly_limit - plan_left, 0)

    used_percent = None
    remaining_percent = None
    if monthly_limit and monthly_limit > 0:
        monthly_usage = monthly_usage or 0
        used_percent = min(max(monthly_usage / monthly_limit * 100, 0.0), 100.0)
        effective_left = (
            total_left
            if total_left is not None
            else (plan_left if plan_left is not None else monthly_limit - monthly_usage)
        )
        remaining_percent = min(
            max(effective_left / monthly_limit * 100, 0.0),
            100.0,
        )

    level = "normal"
    if total_left is not None and total_left <= 0:
        level = "exhausted"
    elif remaining_percent is not None and remaining_percent <= 10:
        level = "critical"
    elif remaining_percent is not None and remaining_percent <= 25:
        level = "warning"

    return {
        "ok": True,
        "status": "ok",
        "plan_name": str(payload.get("plan_name") or "Plano SerpApi"),
        "monthly_limit": monthly_limit,
        "monthly_usage": monthly_usage,
        "plan_searches_left": plan_left,
        "total_searches_left": total_left,
        "extra_credits": extra_credits,
        "last_hour_searches": last_hour,
        "hourly_limit": hourly_limit,
        "used_percent": round(used_percent, 1) if used_percent is not None else None,
        "remaining_percent": (
            round(remaining_percent, 1) if remaining_percent is not None else None
        ),
        "level": level,
    }


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error(message: str, *, status: str = "error") -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "message": message,
    }
