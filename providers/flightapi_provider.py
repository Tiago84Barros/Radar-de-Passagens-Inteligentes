"""FlightAPI.io provider — fonte de preco complementar (fallback).

Usada APENAS quando a TravelPayouts nao tem a rota em cache (free tier pequeno:
~20-100 chamadas; nao desperdicar em rotas ja cobertas).

Endpoints (path-based, sem query string):
  Oneway:    https://api.flightapi.io/onewaytrip/<key>/<orig>/<dest>/<dep>/<ad>/<ch>/<inf>/<cabin>/<cur>
  Roundtrip: https://api.flightapi.io/roundtrip/<key>/<orig>/<dest>/<dep>/<ret>/<ad>/<ch>/<inf>/<cabin>/<cur>

Resposta (estilo Skyscanner):
  itineraries[] -> {leg_ids, pricing_options[].price.amount, pricing_options[].items[].url}
  legs[]        -> {id, origin, destination, duration, stop_count, segment_ids, departure, arrival}
  segments[]    -> {id, marketing_carrier_id, ...}
  carriers[]    -> {id, name}
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests

from app.settings import get_settings
from providers.base_provider import BaseProvider


class FlightApiProvider(BaseProvider):
    name = "flightapi"
    BASE_URL = "https://api.flightapi.io"

    def __init__(self, timeout: int = 25) -> None:
        self.settings = get_settings()
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(getattr(self.settings, "flightapi_key", None))

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "BRL",
        adults: int = 1,
        cabin: str = "Economy",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        key = self.settings.flightapi_key
        o = origin.upper()
        d = destination.upper()
        dep = _date_to_day(departure_date)
        cur = currency.upper()

        if return_date:
            ret = _date_to_day(return_date)
            url = f"{self.BASE_URL}/roundtrip/{key}/{o}/{d}/{dep}/{ret}/{adults}/0/0/{cabin}/{cur}"
        else:
            url = f"{self.BASE_URL}/onewaytrip/{key}/{o}/{d}/{dep}/{adults}/0/0/{cabin}/{cur}"

        try:
            response = requests.get(url, timeout=self.timeout)
            if response.status_code in {401, 403}:
                raise FlightApiProviderError(
                    "Chave da FlightAPI recusada. Confira o secret FLIGHTAPI_KEY.",
                    status_code=response.status_code,
                )
            if response.status_code == 429:
                raise FlightApiProviderError(
                    "Cota da FlightAPI esgotada (free tier). Tente mais tarde.",
                    status_code=429,
                )
            response.raise_for_status()
            payload = response.json()
        except FlightApiProviderError:
            raise
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise FlightApiProviderError(
                "Nao foi possivel consultar a FlightAPI agora.", status_code=status_code
            ) from exc
        except ValueError as exc:
            raise FlightApiProviderError("A FlightAPI retornou resposta invalida.") from exc

        return self.normalize_response(
            payload, origin=o, destination=d,
            departure_date=dep, return_date=_date_to_day(return_date) if return_date else None,
            currency=cur, limit=limit,
        )

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        itineraries = payload.get("itineraries") or []
        legs_by_id = {l.get("id"): l for l in (payload.get("legs") or []) if isinstance(l, dict)}
        carriers_by_id = {
            c.get("id"): (c.get("name") or c.get("display_code") or "")
            for c in (payload.get("carriers") or []) if isinstance(c, dict)
        }

        results: list[dict[str, Any]] = []
        for it in itineraries:
            if not isinstance(it, dict):
                continue
            price = _cheapest_price(it)
            if price is None or price <= 0:
                continue

            leg_ids = it.get("leg_ids") or []
            first_leg = legs_by_id.get(leg_ids[0]) if leg_ids else None

            duration = None
            stops = None
            airline = ""
            if isinstance(first_leg, dict):
                duration = first_leg.get("duration") or first_leg.get("duration_minutes")
                # stops: stop_count, ou (n segmentos - 1)
                if first_leg.get("stop_count") is not None:
                    stops = int(first_leg["stop_count"])
                else:
                    segs = first_leg.get("segment_ids") or []
                    stops = max(len(segs) - 1, 0) if segs else None
                # airline: primeiro carrier do leg
                cid = first_leg.get("marketing_carrier_id") or first_leg.get("carrier_id")
                if cid is not None:
                    airline = carriers_by_id.get(cid, "")

            link = _deep_link(it)

            results.append(
                {
                    "provider": self.name,
                    "source": self.name,
                    "origin": kwargs["origin"],
                    "destination": kwargs["destination"],
                    "departure_date": kwargs["departure_date"],
                    "return_date": kwargs.get("return_date"),
                    "airline": airline,
                    "price": float(price),
                    "currency": kwargs.get("currency", "BRL"),
                    "duration_minutes": int(duration) if duration else None,
                    "stops": stops,
                    "booking_link": link,
                    "raw_payload": {"flightapi": True, "itinerary_id": it.get("id")},
                }
            )

        results.sort(key=lambda r: r["price"])
        return results[: kwargs.get("limit", 20)]


class FlightApiProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _cheapest_price(itinerary: dict) -> float | None:
    prices: list[float] = []
    for opt in itinerary.get("pricing_options") or []:
        if not isinstance(opt, dict):
            continue
        p = opt.get("price")
        amount = None
        if isinstance(p, dict):
            amount = p.get("amount") or p.get("total")
        elif isinstance(p, (int, float, str)):
            amount = p
        try:
            if amount is not None:
                prices.append(float(amount))
        except (TypeError, ValueError):
            continue
    return min(prices) if prices else None


def _deep_link(itinerary: dict) -> str:
    for opt in itinerary.get("pricing_options") or []:
        if not isinstance(opt, dict):
            continue
        for item in opt.get("items") or []:
            if isinstance(item, dict):
                url = item.get("url") or item.get("deep_link") or item.get("booking_url")
                if url:
                    return str(url)
    return ""


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
