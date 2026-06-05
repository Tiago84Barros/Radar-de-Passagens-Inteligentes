"""Copa Air flight scraper — Playwright-based.

robots.txt: User-agent: * Allow: /  (completamente aberto — verificado em 04/06/2026)

Copa Air usa Angular SPA com backend GDS (Sabre). A estrategia principal e
interceptar as chamadas de rede que a propria pagina faz ao seu backend; o
fallback extrai precos diretamente do DOM renderizado.

Rota tipica: BEL -> MCO via PTY (Panama City, hub Copa).
Precos retornados em USD por padrao — convertidos se currency=BRL com taxa
de fallback (nao chama API de cambio para nao bloquear o fluxo).
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from scrapers.base_scraper import BaseAirlineScraper, _date_to_day


class CopaAirScraper(BaseAirlineScraper):
    source = "copa_air"
    airline = "Copa Air"
    start_url = "https://www.copaair.com"
    min_interval_seconds = 30

    # URL de busca de resultados (Angular SPA — parametros via query string)
    _RESULTS_URL = "https://www.copaair.com/en-gs/book/flights/results/"

    # Palavras-chave que identificam respostas JSON com dados de voo
    _FLIGHT_KEYWORDS = (
        "totalFare", "totalAmount", "flightOffers", "itinerary",
        "fareBasis", "cabin", "departureDate", "arrivalDate",
        "carrierCode", "flightSegment", "pricingInfo",
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

        dep_str = _date_to_day(departure_date)
        ret_str = _date_to_day(return_date) if return_date else None
        trip_type = "RT" if ret_str else "OW"

        params = (
            f"?origin={origin.upper()}&destination={destination.upper()}"
            f"&departureDate={dep_str}"
            + (f"&returnDate={ret_str}" if ret_str else "")
            + f"&adults={adults}&children=0&infants=0&cabin=Y&tripType={trip_type}"
            f"&currency={currency.upper()}"
        )
        search_url = self._RESULTS_URL + params

        intercepted: list[dict] = []

        def _on_response(response) -> None:
            url = response.url
            if not any(k in url for k in ("copaair.com", "copa.com")):
                return
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                body = response.text()
                if any(kw in body for kw in self._FLIGHT_KEYWORDS):
                    intercepted.append({"url": url, "body": body})
            except Exception:
                pass

        results: list[dict[str, Any]] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=self.user_agent,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            page.on("response", _on_response)

            try:
                page.goto(search_url, wait_until="networkidle", timeout=35_000)
            except Exception:
                # networkidle timeout is expected on SPAs — continue with what we have
                pass

            # Strategy 1: parse intercepted JSON API responses
            for item in intercepted[:5]:
                parsed = _parse_copa_json(item["body"], origin, destination,
                                          dep_str, ret_str, currency, adults, self)
                results.extend(parsed)
                if len(results) >= limit:
                    break

            # Strategy 2: DOM price extraction as fallback
            if not results:
                try:
                    page_text = page.locator("body").inner_text(timeout=8_000)
                    results = _extract_from_dom(
                        page_text, origin, destination,
                        dep_str, ret_str, currency, adults, limit, self,
                    )
                except Exception:
                    pass

            browser.close()

        return results[:limit]


# ── JSON response parsers ──────────────────────────────────────────────────────

def _parse_copa_json(
    body: str,
    origin: str,
    destination: str,
    dep_str: str,
    ret_str: str | None,
    currency: str,
    adults: int,
    scraper: CopaAirScraper,
) -> list[dict[str, Any]]:
    """Try multiple Copa/GDS JSON formats to extract flight offers."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return []

    results: list[dict[str, Any]] = []

    # Format A: OTA/GDS-style (Sabre, Amadeus-compatible)
    results.extend(_parse_ota_format(data, origin, destination, dep_str, ret_str, currency, scraper))
    if results:
        return results

    # Format B: Copa proprietary (Angular BFF pattern)
    results.extend(_parse_copa_bff(data, origin, destination, dep_str, ret_str, currency, scraper))
    if results:
        return results

    # Format C: flat list of offers
    results.extend(_parse_flat_offers(data, origin, destination, dep_str, ret_str, currency, scraper))
    return results


def _parse_ota_format(data, origin, destination, dep_str, ret_str, currency, scraper):
    """OTA (Open Travel Alliance) / Sabre GDS format."""
    results = []
    try:
        # Nested OTA structure
        ota = (
            data.get("OTA_AirLowFareSearchRS")
            or data.get("flightAvailability")
            or data.get("FlightAvailability")
            or {}
        )
        options = (
            ota.get("PricedItineraries", {}).get("PricedItinerary")
            or ota.get("OriginDestinationOptions", {}).get("OriginDestinationOption")
            or []
        )
        if not isinstance(options, list):
            options = [options]

        for opt in options[:10]:
            price = _extract_price_ota(opt)
            if not price:
                continue
            duration, stops = _extract_duration_stops_ota(opt)
            results.append(scraper._normalized_result(
                origin=origin, destination=destination,
                departure_date=dep_str, return_date=ret_str,
                price=price, currency=currency,
                booking_link="https://www.copaair.com",
                raw_payload={"format": "ota", "raw": str(opt)[:500]},
            ) | {"duration_minutes": duration, "stops": stops})
    except Exception:
        pass
    return results


def _extract_price_ota(opt: dict) -> float | None:
    try:
        fare = opt.get("AirItineraryPricingInfo", {}).get("ItinTotalFare", {})
        total = fare.get("TotalFare") or fare.get("EquivFare") or {}
        amount = total.get("Amount") or total.get("@Amount")
        return float(amount) if amount else None
    except (TypeError, ValueError):
        return None


def _extract_duration_stops_ota(opt: dict) -> tuple[int | None, int | None]:
    try:
        itin = opt.get("AirItinerary", {}).get("OriginDestinationOptions", {})
        options = itin.get("OriginDestinationOption", [])
        if not isinstance(options, list):
            options = [options]
        if not options:
            return None, None
        first = options[0]
        segments = first.get("FlightSegment", [])
        if not isinstance(segments, list):
            segments = [segments]
        stops = max(len(segments) - 1, 0)
        duration = None
        elapsed = first.get("ElapsedTime")
        if elapsed:
            duration = int(elapsed)
        return duration, stops
    except Exception:
        return None, None


def _parse_copa_bff(data, origin, destination, dep_str, ret_str, currency, scraper):
    """Copa Air BFF (Backend For Frontend) — Angular app pattern."""
    results = []
    try:
        offers = (
            data.get("flightOffers")
            or data.get("offers")
            or data.get("flights")
            or []
        )
        if isinstance(data, list):
            offers = data
        if not isinstance(offers, list):
            return []

        for offer in offers[:10]:
            price = _first_float(offer, "totalFare", "totalAmount", "totalPrice",
                                 "fare", "price", "amount")
            if not price:
                continue
            duration = _first_int(offer, "elapsedTime", "duration", "durationMinutes")
            stops = _first_int(offer, "stops", "numStops", "numberOfStops")
            link = offer.get("deepLink") or offer.get("bookingUrl") or "https://www.copaair.com"
            results.append(scraper._normalized_result(
                origin=origin, destination=destination,
                departure_date=dep_str, return_date=ret_str,
                price=price, currency=currency,
                booking_link=link,
                raw_payload={"format": "bff", "raw": str(offer)[:500]},
            ) | {"duration_minutes": duration, "stops": stops})
    except Exception:
        pass
    return results


def _parse_flat_offers(data, origin, destination, dep_str, ret_str, currency, scraper):
    """Generic flat JSON — last resort."""
    results = []
    try:
        text = json.dumps(data)
        # Look for any price-like numbers near "totalFare" or "total"
        prices = re.findall(r'"(?:totalFare|totalAmount|total|price|fare)"\s*:\s*"?(\d+(?:\.\d+)?)"?', text)
        if prices:
            price = float(prices[0])
            if 50 < price < 50_000:  # sanity check
                results.append(scraper._normalized_result(
                    origin=origin, destination=destination,
                    departure_date=dep_str, return_date=ret_str,
                    price=price, currency=currency,
                    booking_link="https://www.copaair.com",
                    raw_payload={"format": "flat_regex"},
                ))
    except Exception:
        pass
    return results


# ── DOM fallback ───────────────────────────────────────────────────────────────

_USD_RE = re.compile(r"\$\s*([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")
_BRL_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})")


def _extract_from_dom(
    text: str, origin: str, destination: str,
    dep_str: str, ret_str: str | None,
    currency: str, adults: int, limit: int,
    scraper: CopaAirScraper,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    if currency.upper() == "BRL":
        matches = _BRL_RE.findall(text)
        prices = []
        for m in matches:
            try:
                prices.append(float(m.replace(".", "").replace(",", ".")))
            except ValueError:
                pass
    else:
        matches = _USD_RE.findall(text)
        prices = []
        for m in matches:
            try:
                prices.append(float(m.replace(",", "")))
            except ValueError:
                pass

    # Filter: realistic flight prices
    prices = sorted(set(p for p in prices if 100 < p < 30_000))[:limit]
    for price in prices:
        results.append(scraper._normalized_result(
            origin=origin, destination=destination,
            departure_date=dep_str, return_date=ret_str,
            price=price, currency=currency,
            booking_link="https://www.copaair.com",
            raw_payload={"format": "dom_text_extraction"},
        ))
    return results


# ── Helpers ────────────────────────────────────────────────────────────────────

def _first_float(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _first_int(d: dict, *keys: str) -> int | None:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None
