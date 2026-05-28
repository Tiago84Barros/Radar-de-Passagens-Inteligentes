from __future__ import annotations

import re
from typing import Any


def extract_brl_price(text: str) -> float | None:
    match = re.search(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})", text)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def run_safe_playwright_search(scraper: Any, origin: str, destination: str, departure_date, return_date, currency: str, adults: int) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=scraper.user_agent)
            page.goto(scraper.start_url, wait_until="domcontentloaded", timeout=30000)
            _fill_first_available(page, ["input[name*=origin i]", "input[placeholder*=origem i]", "input[aria-label*=origem i]"], origin)
            _fill_first_available(page, ["input[name*=destination i]", "input[placeholder*=destino i]", "input[aria-label*=destino i]"], destination)
            _fill_first_available(page, ["input[type=date]", "input[name*=departure i]", "input[placeholder*=ida i]"], str(departure_date)[:10])
            price = extract_brl_price(page.locator("body").inner_text(timeout=5000))
            if price is None:
                return []
            return [
                scraper._normalized_result(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    price=price,
                    currency=currency,
                    booking_link=page.url,
                    raw_payload={"scraper": scraper.source, "controlled": True},
                )
            ]
        finally:
            browser.close()


def _fill_first_available(page, selectors: list[str], value: str) -> None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first()
            if locator.count() > 0 and locator.is_visible(timeout=1500):
                locator.fill(value, timeout=3000)
                return
        except Exception:
            continue
