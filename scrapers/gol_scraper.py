from __future__ import annotations

from scrapers.base_scraper import BaseAirlineScraper
from scrapers.browser_helpers import run_safe_playwright_search


class GolScraper(BaseAirlineScraper):
    source = "gol"
    airline = "GOL"
    start_url = "https://www.voegol.com.br/"

    def _search_with_playwright(self, origin, destination, departure_date, return_date, currency, adults, limit):
        return run_safe_playwright_search(self, origin, destination, departure_date, return_date, currency, adults)
