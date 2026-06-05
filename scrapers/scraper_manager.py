from __future__ import annotations

from typing import Any

from app.settings import get_settings
from scrapers.azul_scraper import AzulScraper
from scrapers.base_scraper import ScraperError
from scrapers.copa_scraper import CopaAirScraper
from scrapers.gol_scraper import GolScraper
from scrapers.google_flights_scraper import GoogleFlightsScraper
from scrapers.latam_scraper import LatamScraper


_LAST_SCRAPER_DIAGNOSTICS: list[dict[str, str]] = []


def configured_scrapers() -> list:
    settings = get_settings()
    if not settings.enable_airline_scrapers:
        return []
    # Copa Air has a fully open robots.txt (Allow: /) and serves BEL→MCO via PTY
    # hub — included by default when scrapers are enabled.
    # Google Flights, Azul, GOL, LATAM run alongside but may return 0 results
    # due to anti-bot protection on datacenter IPs.
    return [
        CopaAirScraper(),
        GoogleFlightsScraper(),
        AzulScraper(),
        GolScraper(),
        LatamScraper(),
    ]


def search_all_scrapers(search_params: dict[str, Any]) -> list[dict[str, Any]]:
    global _LAST_SCRAPER_DIAGNOSTICS
    results: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    for scraper in configured_scrapers():
        try:
            items = scraper.search_flights(
                origin=search_params["origin"],
                destination=search_params["destination"],
                departure_date=search_params["departure_date"],
                return_date=search_params.get("return_date"),
                currency=search_params.get("currency", "BRL"),
                adults=int(search_params.get("adults") or search_params.get("passengers") or 1),
                limit=search_params.get("limit", 20),
            )
            results.extend(items)
            diagnostics.append({"source": scraper.source, "status": "ok", "message": f"{len(items)} cotacao(oes)"})
        except ScraperError as exc:
            diagnostics.append({"source": scraper.source, "status": "failed", "message": str(exc)[:240]})
        except Exception as exc:  # noqa: BLE001
            diagnostics.append({"source": scraper.source, "status": "failed", "message": f"Erro controlado no scraper: {exc}"[:240]})
    if not diagnostics and not get_settings().enable_airline_scrapers:
        diagnostics.append({"source": "scrapers", "status": "disabled", "message": "ENABLE_AIRLINE_SCRAPERS=false"})
    _LAST_SCRAPER_DIAGNOSTICS = diagnostics
    return results


def get_last_scraper_diagnostics() -> list[dict[str, str]]:
    return list(_LAST_SCRAPER_DIAGNOSTICS)
