from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


class ScraperError(RuntimeError):
    pass


class BaseAirlineScraper(ABC):
    source: str
    airline: str
    start_url: str
    min_interval_seconds = 45
    user_agent = "RadarDePassagensBot/1.0 (+controlled monitoring; contact site owner if needed)"
    _last_access_at: float = 0.0

    def is_enabled(self) -> bool:
        return True

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "BRL",
        adults: int = 1,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled() or not self._robots_allows(self.start_url):
            return []
        self._respect_rate_limit()
        return self._search_with_playwright(origin, destination, departure_date, return_date, currency, adults, limit)

    @abstractmethod
    def _search_with_playwright(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None,
        currency: str,
        adults: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self.__class__._last_access_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self.__class__._last_access_at = time.monotonic()

    def _robots_allows(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            response = requests.get(robots_url, timeout=8, headers={"User-Agent": self.user_agent})
            if response.status_code >= 400:
                return True
            parser.parse(response.text.splitlines())
        except requests.RequestException:
            return True
        return parser.can_fetch(self.user_agent, url)

    def _normalized_result(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None,
        price: float,
        currency: str,
        booking_link: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "source": self.source,
            "provider": self.source,
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_date": _date_to_day(departure_date),
            "return_date": _date_to_day(return_date) if return_date else None,
            "airline": self.airline,
            "price": float(price),
            "currency": currency.upper(),
            "duration_minutes": None,
            "stops": None,
            "booking_link": booking_link,
            "raw_payload": raw_payload or {},
        }


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
