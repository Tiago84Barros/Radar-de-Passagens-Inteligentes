from __future__ import annotations

from datetime import date
from typing import Any

import requests

from app.settings import get_settings
from providers.base_provider import BaseProvider


class TravelPayoutsProvider(BaseProvider):
    name = "travelpayouts"
    BASE_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"

    def __init__(self, timeout: int = 20) -> None:
        self.settings = get_settings()
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.settings.travelpayouts_api_token)

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "brl",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        params = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_at": _date_to_month(departure_date),
            "currency": currency.lower(),
            "limit": limit,
            "token": self.settings.travelpayouts_api_token,
            "sorting": "price",
            "one_way": "false" if return_date else "true",
        }
        if return_date:
            params["return_at"] = _date_to_month(return_date)

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise TravelPayoutsProviderError("Não foi possível consultar a Travelpayouts agora.") from exc
        except ValueError as exc:
            raise TravelPayoutsProviderError("A Travelpayouts retornou uma resposta inválida.") from exc

        return self.normalize_response(
            payload,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            currency=currency,
        )

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        data = payload.get("data", []) if isinstance(payload, dict) else []
        results: list[dict[str, Any]] = []
        for item in data:
            price = item.get("price")
            if price is None:
                continue
            departure_at = item.get("departure_at") or kwargs["departure_date"]
            return_at = item.get("return_at") or kwargs.get("return_date")
            link = item.get("link") or ""
            results.append(
                {
                    "provider": self.name,
                    "origin": (item.get("origin") or kwargs["origin"]).upper(),
                    "destination": (item.get("destination") or kwargs["destination"]).upper(),
                    "departure_date": _date_to_day(departure_at),
                    "return_date": _date_to_day(return_at) if return_at else None,
                    "airline": item.get("airline") or "",
                    "price": float(price),
                    "currency": str(item.get("currency") or kwargs.get("currency") or "BRL").upper(),
                    "duration_minutes": item.get("duration"),
                    "stops": item.get("transfers"),
                    "booking_link": f"https://www.aviasales.com{link}" if link.startswith("/") else link,
                    "raw_payload": item,
                }
            )
        return results


class TravelPayoutsProviderError(RuntimeError):
    pass


def _date_to_month(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:7]


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
