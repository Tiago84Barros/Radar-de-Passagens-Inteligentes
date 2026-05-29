from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote_plus

from scrapers.base_scraper import BaseAirlineScraper

# Matches "R$ 1.234" or "R$ 1.234,56"
_PRICE_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)")

# Common Brazilian airline names that may appear in result aria-labels
_KNOWN_AIRLINES = ["LATAM", "GOL", "Azul", "TAP", "Iberia", "American", "United", "Air France", "Avianca", "Copa"]


class GoogleFlightsScraper(BaseAirlineScraper):
    source = "google_flights"
    airline = "Google Flights"
    start_url = "https://www.google.com/travel/flights"
    min_interval_seconds = 25

    def _build_url(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None,
    ) -> str:
        dep = _date_to_day(departure_date)
        if return_date:
            query = f"Voos de {origin} para {destination} ida {dep} volta {_date_to_day(return_date)}"
        else:
            query = f"Voos de {origin} para {destination} ida {dep} somente ida"
        return (
            f"{self.start_url}?q={quote_plus(query)}"
            f"&curr=BRL&hl=pt-BR&gl=BR"
        )

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
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        url = self._build_url(origin, destination, departure_date, return_date)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--lang=pt-BR", "--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="pt-BR",
                    extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9"},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                self._handle_consent(page)

                # Wait for at least one price to render (Google Flights is a heavy SPA)
                body_text = self._wait_for_prices(page, timeout_ms=30000)
                if not body_text:
                    return []

                prices = _extract_prices(body_text)
                if not prices:
                    return []

                cheapest = min(prices)
                airline = _detect_airline(body_text)

                result = self._normalized_result(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    price=cheapest,
                    currency="BRL",
                    booking_link=page.url,
                    raw_payload={
                        "scraper": self.source,
                        "all_prices": prices[:10],
                        "query_url": url,
                    },
                )
                if airline:
                    result["airline"] = airline
                return [result]
            finally:
                browser.close()

    def _handle_consent(self, page) -> None:
        """Dismiss Google's cookie/consent interstitial, preferring to reject."""
        if "consent." not in page.url:
            return
        for label in ["Rejeitar tudo", "Reject all", "Recusar tudo", "Aceitar tudo", "Accept all"]:
            try:
                btn = page.get_by_role("button", name=label)
                if btn.count() > 0:
                    btn.first.click(timeout=4000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    return
            except Exception:
                continue

    def _wait_for_prices(self, page, timeout_ms: int) -> str:
        """Poll the page body until a R$ price appears or timeout."""
        import time

        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                text = ""
            if _PRICE_RE.search(text):
                return text
            page.wait_for_timeout(1500)
        return ""


def _extract_prices(text: str) -> list[float]:
    prices: list[float] = []
    for match in _PRICE_RE.finditer(text):
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        # Ignore implausible values (UI noise, ratings, etc.)
        if 80 <= value <= 100_000:
            prices.append(value)
    return prices


def _detect_airline(text: str) -> str:
    for name in _KNOWN_AIRLINES:
        if name.lower() in text.lower():
            return name
    return ""


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
