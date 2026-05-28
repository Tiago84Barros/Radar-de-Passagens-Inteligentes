from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from app.settings import get_settings
from services.amadeus_provider import AmadeusProvider


@dataclass(frozen=True)
class FlightOffer:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    airline: str
    price: float
    currency: str
    duration_minutes: int
    stops: int
    booking_link: str
    provider: str


def _mock_offers(provider: str, query: dict, base_price: int) -> list[FlightOffer]:
    seed = f"{provider}:{query['origin']}:{query['destination']}:{query['departure_date']}:{query['passengers']}"
    rng = Random(seed)
    destination = "LIS" if query["destination"] == "ANYWHERE" else query["destination"].upper()
    airlines = ["LATAM", "GOL", "Azul", "TAP", "Iberia"]
    offers = []
    for index in range(3):
        price = round((base_price + rng.randint(-220, 280) + index * 70) * query["passengers"], 2)
        offers.append(
            FlightOffer(
                origin=query["origin"].upper(),
                destination=destination,
                departure_date=query["departure_date"],
                return_date=query.get("return_date"),
                airline=airlines[(rng.randint(0, 10) + index) % len(airlines)],
                price=max(price, 199.0),
                currency=query["currency"].upper(),
                duration_minutes=rng.randint(110, 780),
                stops=rng.choice([0, 0, 1, 1, 2]),
                booking_link=f"https://example.com/{provider}/{query['origin']}-{destination}-{query['departure_date'] + timedelta(days=index)}",
                provider=provider,
            )
        )
    return sorted(offers, key=lambda offer: offer.price)


def search_amadeus(query: dict) -> list[FlightOffer]:
    settings = get_settings()
    if not settings.amadeus_client_id or not settings.amadeus_client_secret:
        return _mock_offers("amadeus_mock", query, 1450)
    try:
        offers = AmadeusProvider().search_flights(query)
    except Exception:  # noqa: BLE001
        return _mock_offers("amadeus_error_mock", query, 1450)
    return [
        FlightOffer(
            origin=offer["origin"],
            destination=offer["destination"],
            departure_date=offer["departure_date"],
            return_date=offer["return_date"],
            airline=offer["airline"],
            price=offer["price"],
            currency=offer["currency"],
            duration_minutes=offer["duration_minutes"],
            stops=offer["stops"],
            booking_link=offer["booking_link"],
            provider=offer["provider"],
        )
        for offer in offers
    ] or _mock_offers("amadeus_empty_mock", query, 1450)


def search_kiwi(query: dict) -> list[FlightOffer]:
    settings = get_settings()
    if not settings.kiwi_api_key:
        return _mock_offers("kiwi_mock", query, 1320)
    return _mock_offers("kiwi_ready", query, 1320)


def search_travelpayouts(query: dict) -> list[FlightOffer]:
    settings = get_settings()
    if not settings.travelpayouts_token:
        return _mock_offers("travelpayouts_mock", query, 1390)
    return _mock_offers("travelpayouts_ready", query, 1390)


def search_all_providers(query: dict) -> list[FlightOffer]:
    offers: list[FlightOffer] = []
    for fn in (search_amadeus, search_kiwi, search_travelpayouts):
        offers.extend(fn(query))
    return sorted(offers, key=lambda offer: offer.price)
