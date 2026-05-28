from __future__ import annotations

import re
from datetime import date
from typing import Any

import httpx

from app.settings import get_settings


class AmadeusProvider:
    TOKEN_PATH = "/v1/security/oauth2/token"
    FLIGHT_OFFERS_PATH = "/v2/shopping/flight-offers"

    def __init__(self, timeout: float = 20) -> None:
        self.settings = get_settings()
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        if self.settings.amadeus_env == "production":
            return "https://api.amadeus.com"
        return "https://test.api.amadeus.com"

    def is_configured(self) -> bool:
        return bool(self.settings.amadeus_client_id and self.settings.amadeus_client_secret)

    def get_access_token(self) -> str:
        if not self.is_configured():
            raise AmadeusConfigurationError("Credenciais da Amadeus não configuradas.")

        response = httpx.post(
            f"{self.base_url}{self.TOKEN_PATH}",
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.amadeus_client_id,
                "client_secret": self.settings.amadeus_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AmadeusConnectionError("A Amadeus recusou a autenticação. Confira o ambiente e as credenciais.") from exc

        token = response.json().get("access_token")
        if not token:
            raise AmadeusConnectionError("A Amadeus não retornou um token de acesso.")
        return token

    def search_flights(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        token = self.get_access_token()
        params = self._build_search_params(query)
        response = httpx.get(
            f"{self.base_url}{self.FLIGHT_OFFERS_PATH}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AmadeusConnectionError("Não foi possível buscar ofertas na Amadeus para essa rota.") from exc
        return self._parse_flight_offers(response.json(), query)

    def _build_search_params(self, query: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "originLocationCode": str(query["origin"]).upper(),
            "destinationLocationCode": str(query["destination"]).upper(),
            "departureDate": _date_to_iso(query["departure_date"]),
            "adults": int(query.get("passengers") or 1),
            "currencyCode": str(query.get("currency") or "BRL").upper(),
            "max": 10,
        }
        if query.get("return_date"):
            params["returnDate"] = _date_to_iso(query["return_date"])
        if query.get("max_price"):
            params["maxPrice"] = int(float(query["max_price"]))
        return params

    def _parse_flight_offers(self, payload: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
        offers = []
        dictionaries = payload.get("dictionaries") or {}
        carriers = dictionaries.get("carriers") or {}
        for offer in payload.get("data", []):
            itineraries = offer.get("itineraries") or []
            first_itinerary = itineraries[0] if itineraries else {}
            segments = first_itinerary.get("segments") or []
            first_segment = segments[0] if segments else {}
            carrier_code = first_segment.get("carrierCode") or "Amadeus"
            price = offer.get("price") or {}
            offers.append(
                {
                    "origin": str(query["origin"]).upper(),
                    "destination": str(query["destination"]).upper(),
                    "departure_date": query["departure_date"],
                    "return_date": query.get("return_date"),
                    "airline": carriers.get(carrier_code, carrier_code),
                    "price": float(price.get("grandTotal") or price.get("total") or 0),
                    "currency": price.get("currency") or str(query.get("currency") or "BRL").upper(),
                    "duration_minutes": _duration_to_minutes(first_itinerary.get("duration")),
                    "stops": max(len(segments) - 1, 0),
                    "booking_link": "https://www.amadeus.com/",
                    "provider": "amadeus",
                }
            )
        return sorted([offer for offer in offers if offer["price"] > 0], key=lambda item: item["price"])


class AmadeusConfigurationError(RuntimeError):
    pass


class AmadeusConnectionError(RuntimeError):
    pass


def _date_to_iso(value: date | Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _duration_to_minutes(value: str | None) -> int:
    if not value:
        return 0
    match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?", value)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes
