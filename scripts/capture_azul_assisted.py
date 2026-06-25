from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from services.official_capture_parser import parse_azul_visible_fares
from services.official_search_links import build_official_search_links


def main() -> int:
    args = _parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright nao esta instalado. Rode: pip install playwright && playwright install chromium")
        return 2

    source_url = args.url or _default_azul_url(args)
    if not source_url:
        print("Nao foi possivel montar a URL da Azul.")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(locale="pt-BR")
        page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
        print("A pagina da Azul foi aberta.")
        print("Se aparecer login, CAPTCHA ou selecao adicional, resolva manualmente no navegador.")
        input("Quando a lista de voos estiver visivel, pressione Enter aqui para capturar... ")
        visible_text = page.locator("body").inner_text(timeout=15000)
        browser.close()

    fares = parse_azul_visible_fares(
        visible_text,
        origin=args.origin,
        destination=args.destination,
        departure_date=args.departure_date,
        source_url=source_url,
    )
    payload = {
        "source": "azul_assisted_browser",
        "source_url": source_url,
        "origin": args.origin.upper(),
        "destination": args.destination.upper(),
        "departure_date": args.departure_date,
        "fares": fares,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
        print(f"Captura salva em {path}")
    else:
        print(output)
    return 0


def _default_azul_url(args: argparse.Namespace) -> str:
    links = build_official_search_links(
        {
            "origin_iata": args.origin,
            "destination_iata": args.destination,
            "departure_date": args.departure_date,
            "return_date": args.return_date,
            "adults": args.adults,
        }
    )
    return next((link["url"] for link in links if link["label"] == "Azul"), "")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Captura assistida de tarifas visiveis da Azul.")
    parser.add_argument("--origin", required=True, help="Origem IATA, ex.: BEL")
    parser.add_argument("--destination", required=True, help="Destino IATA, ex.: FOR")
    parser.add_argument("--departure-date", required=True, help="Data do trecho YYYY-MM-DD")
    parser.add_argument("--return-date", help="Data de volta YYYY-MM-DD, usada apenas para montar a URL")
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--url", help="URL da pagina da Azul ja aberta/preenchida")
    parser.add_argument("--output", help="Arquivo JSON de saida")
    args = parser.parse_args()
    _validate_day(args.departure_date)
    if args.return_date:
        _validate_day(args.return_date)
    args.origin = args.origin.upper().strip()
    args.destination = args.destination.upper().strip()
    return args


def _validate_day(value: str) -> None:
    date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
