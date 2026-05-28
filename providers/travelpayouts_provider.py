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
            "page": 1,
            "token": self.settings.travelpayouts_api_token,
            "sorting": "price",
            "one_way": "false" if return_date else "true",
        }
        if return_date:
            params["return_at"] = _date_to_month(return_date)

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=self.timeout)
            if response.status_code in {401, 403}:
                raise TravelPayoutsProviderError(
                    "Token da Travelpayouts recusado. Confira se o secret TRAVELPAYOUTS_API_TOKEN esta correto.",
                    status_code=response.status_code,
                )
            response.raise_for_status()
            payload = response.json()
        except TravelPayoutsProviderError:
            raise
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise TravelPayoutsProviderError(
                "Nao foi possivel consultar a Travelpayouts agora. Tente novamente em alguns minutos.",
                status_code=status_code,
            ) from exc
        except ValueError as exc:
            raise TravelPayoutsProviderError("A Travelpayouts retornou uma resposta invalida.") from exc

        if isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error") or payload.get("errors") or "resposta sem sucesso"
            raise TravelPayoutsProviderError(f"A Travelpayouts recusou a consulta: {_safe_error_text(error)}")

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
                    "source": self.name,
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
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _safe_error_text(value: Any) -> str:
    text = str(value)
    token = get_settings().travelpayouts_api_token or ""
    if token:
        text = text.replace(token, "[token oculto]")
    return text[:240]


def _date_to_month(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:7]


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
